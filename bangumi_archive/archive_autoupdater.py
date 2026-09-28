import os
import zipfile
import requests
import json
import tempfile
from pathlib import Path
from config.config import ARCHIVE_FILES_DIR
from tools.log import logger
from bangumi_archive.sqlite_store import ArchiveStore
from tools.cache_time import TimeCacheManager
from tools.file_lock import exclusive_file_lock
from tools.proxy_settings import proxy_kwargs


def _proxy(url):
    from config import config
    return proxy_kwargs(url, {"OUTBOUND_PROXY_URL": getattr(config, "OUTBOUND_PROXY_URL", "")})


UpdateTimeCacheFilePath = os.path.join(
    ARCHIVE_FILES_DIR, "archive_update_time.json")


def file_integrity_verifier(file_path, expected_hash=None, expected_size=None):
    """文件完整性验证工具"""
    # 分块哈希校验
    import hashlib
    if expected_hash:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        if sha256_hash.hexdigest() != expected_hash:
            logger.error(f"哈希校验失败: 文件 {file_path} 可能损坏或被篡改")
            return False

    # 验证文件大小
    if expected_size and os.path.getsize(file_path) != expected_size:
        logger.error(
            f"文件大小验证失败: 预期 {expected_size} 字节, 实际 {os.path.getsize(file_path)} 字节"
        )
        return False

    # ZIP 完整性自检
    if file_path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(file_path) as zip_ref:
                if zip_ref.testzip() is not None:
                    logger.error(f"压缩文件 CRC 校验失败: {file_path} 文件损坏")
                    return False
        except Exception as e:
            logger.error(f"压缩文件无法读取: {file_path} 文件损坏")
            return False

    return True


def get_latest_url_update_time_and_size():
    """获取最新Archive文件下载地址, 更新时间和文件尺寸"""
    try:
        url = "https://raw.githubusercontent.com/bangumi/Archive/master/aux/latest.json"
        response = requests.get(url, timeout=20, **_proxy(url))
        response.raise_for_status()
        data = response.json()
        return (
            data.get("browser_download_url"),
            data.get("updated_at"),
            data.get("size"),
        )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Bangumi Archive JSON 获取失败: {e}")
    except json.JSONDecodeError as e:
        logger.warning(f"Bangumi Archive JSON 解析失败: {e}")
    except Exception as e:
        logger.warning(f"Bangumi Archive JSON 获取失败: {e}")
    return "", "", ""


def update_index():
    return ArchiveStore(ARCHIVE_FILES_DIR).build()


def update_archive(url, target_dir=ARCHIVE_FILES_DIR, expected_size=None):
    """下载并解压文件"""
    import tqdm
    os.makedirs(target_dir, exist_ok=True)
    temp_zip_path = os.path.join(target_dir, "temp_archive.zip")
    logger.info("正在下载 Bangumi Archive 数据......")
    try:
        # 下载文件
        response = requests.get(url, stream=True, timeout=(10, 60), **_proxy(url))
        response.raise_for_status()
        # 获取文件尺寸
        if not expected_size:
            expected_size = int(response.headers.get("content-length", 0))

        # 添加 tqdm 下载进度条
        with open(temp_zip_path, "wb") as f, tqdm.tqdm(
            total=expected_size,
            unit="B",
            unit_scale=True,
            desc="正在下载",
            leave=True,
        ) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                pbar.update(len(chunk))

        if not file_integrity_verifier(
            file_path=temp_zip_path, expected_size=expected_size
        ):
            raise Exception("下载的Archive文件不完整")
        logger.info(f"Bangumi Archive 压缩包下载成功: {temp_zip_path}")

        # Validate and index in isolation before replacing any active data.
        with tempfile.TemporaryDirectory(prefix="archive-stage-", dir=target_dir) as stage:
            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                for filename in ("subject.jsonlines", "subject-relations.jsonlines"):
                    info = zip_ref.getinfo(filename)
                    if info.file_size > 8 * 1024**3:
                        raise ValueError("归档文件超过允许大小")
                    import shutil
                    with zip_ref.open(info) as source, open(Path(stage) / filename, "wb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
            ArchiveStore(stage).build()
            for filename in ("subject.jsonlines", "subject-relations.jsonlines", "bangumi.sqlite3"):
                os.replace(Path(stage) / filename, Path(target_dir) / filename)
        logger.info(f"Bangumi Archive 成功解压到: {target_dir}")

    except Exception as e:
        logger.error(f"Bangumi Archive 下载/解压失败: {str(e)}")
        return False
    finally:
        # 移除Archive压缩包
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
    return True


def check_archive():
    os.makedirs(ARCHIVE_FILES_DIR, exist_ok=True)
    with exclusive_file_lock(Path(ARCHIVE_FILES_DIR) / "archive-update.lock"):
        return _check_archive_locked()


def _check_archive_locked():
    needs_repair = False
    if (Path(ARCHIVE_FILES_DIR) / "subject.jsonlines").exists():
        try:
            update_index()
        except Exception as exc:
            needs_repair = True
            logger.warning("本地归档索引构建失败，保留旧索引并尝试重新下载：%s", exc)

    download_url, latest_update_time, zip_file_size = (
        get_latest_url_update_time_and_size()
    )
    if download_url == "":
        logger.warning("无法获取 Bangumi Archive 下载链接, 跳过Archive更新")
        return False

    # 读取本地缓存时间
    local_update_time = TimeCacheManager.convert_to_datetime(
        TimeCacheManager.read_time(UpdateTimeCacheFilePath)
    )
    remote_update_time = TimeCacheManager.convert_to_datetime(
        latest_update_time)
    if needs_repair or not ArchiveStore(ARCHIVE_FILES_DIR).ready() or remote_update_time > local_update_time:
        logger.info("检测到新版本 Bangumi Archive, 开始更新...")
        if update_archive(download_url, ARCHIVE_FILES_DIR, zip_file_size):
            # 更新索引文件
            update_index()
            TimeCacheManager.save_time(
                UpdateTimeCacheFilePath, latest_update_time)
            logger.info("Bangumi Archive 更新完成")
            return True
        else:
            logger.warning("Bangumi Archive 更新失败")
            return False
    else:
        logger.info("Bangumi Archive 已是最新数据, 无需更新")
        return ArchiveStore(ARCHIVE_FILES_DIR).ready()

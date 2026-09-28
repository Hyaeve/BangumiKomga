# -*- coding: utf-8 -*- #
# ------------------------------------------------------------------
# Description: Bangumi API(https://github.com/bangumi/api)
# ------------------------------------------------------------------

import requests
from requests.adapters import HTTPAdapter
from tools.proxy_settings import proxy_kwargs

from api.bangumi_model import BangumiBaseType
from tools.log import logger
from bangumi_archive.local_archive_searcher import (
    parse_infobox,
)
from tools.resort_search_results_list import resort_search_list
from tools.slide_window_rate_limiter import slide_window_rate_limiter
from zhconv import convert
from abc import ABC, abstractmethod

# TODO： 在DataSource中添加一个本地缓存目录，将从 API 获取的封面图片保存为文件（如 cache/thumbnails/{subject_id}_{image_size}.jpg），下次直接读取本地文件，避免重复请求


class DataSource(ABC):
    """
    数据源基类
    """

    @abstractmethod
    def search_subjects(self, query, threshold=80, is_novel=False):
        pass

    @abstractmethod
    def get_subject_metadata(self, subject_id):
        pass

    @abstractmethod
    def get_related_subjects(self, subject_id):
        pass

    @abstractmethod
    def update_reading_progress(self, subject_id, progress):
        pass

    @abstractmethod
    def get_subject_thumbnail(self, subject_metadata, image_size):
        pass


class BangumiApiDataSource(DataSource):
    """
    Bangumi API 数据源类
    """

    BASE_URL = "https://api.bgm.tv"

    def __init__(self, access_token=None, proxy_url=""):
        self.r = requests.Session()
        self.proxy_settings = {"OUTBOUND_PROXY_URL": proxy_url}
        self.r.mount("http://", HTTPAdapter(max_retries=3))
        self.r.mount("https://", HTTPAdapter(max_retries=3))
        self.access_token = access_token
        if self.access_token:
            self.refresh_token()

    def _get_headers(self):
        headers = {
            "User-Agent": "chu-shen/BangumiKomga (https://github.com/chu-shen/BangumiKomga)"
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def refresh_token(self):
        # https://bgm.tv/dev/app
        # https://next.bgm.tv/demo/access-token
        return

    @slide_window_rate_limiter()
    def search_subjects(self, query, threshold=80, is_novel=False):
        """
        获取搜索结果，并移除非漫画系列。返回具有完整元数据的条目
        """
        # 正面例子：魔女與使魔 -> 魔女与使魔，325236
        # 反面例子：君は淫らな僕の女王 -> 君は淫らな仆の女王，47331
        url = f"{self.BASE_URL}/v0/search/subjects?limit=20"
        payload = {"keyword": query, "filter": {"type": [BangumiBaseType.BOOK.value]}}

        try:
            response = self.r.post(url, headers=self._get_headers(), json=payload, **proxy_kwargs(url, self.proxy_settings))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"出现错误: {e}")
            return []

        # e.g. Artbooks.VOL.14 -> {"request":"\/search\/subject\/Artbooks.VOL.14?responseGroup=large&type=1","code":404,"error":"Not Found"}
        try:
            response_json = response.json()
        except ValueError as e:
            # bangumi无结果但返回正常
            logger.warning(f"{query}: 404 Not Found")
            return []
        else:
            results = response_json["data"]

        from tools.komf_matching import match_bangumi
        return match_bangumi(query, results, is_novel, offline=False,
                             detail_loader=getattr(self, "matching_detail_source", self.get_subject_metadata))

    @slide_window_rate_limiter()
    def get_subject_metadata(self, subject_id):
        """
        获取漫画元数据
        """
        url = f"{self.BASE_URL}/v0/subjects/{subject_id}"
        try:
            response = self.r.get(url, headers=self._get_headers(), **proxy_kwargs(url, self.proxy_settings))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"An error occurred: {e}")
            logger.error(
                f"请检查 {subject_id} 是否填写正确；或属于 NSFW，但并未配置 BANGUMI_ACCESS_TOKEN"
            )
            return []
        return response.json()

    @slide_window_rate_limiter()
    def get_related_subjects(self, subject_id):
        """
        获取漫画的关联条目
        """
        url = f"{self.BASE_URL}/v0/subjects/{subject_id}/subjects"
        try:
            response = self.r.get(url, headers=self._get_headers(), **proxy_kwargs(url, self.proxy_settings))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"出现错误: {e}")
            return []
        return response.json()

    @slide_window_rate_limiter()
    def update_reading_progress(self, subject_id, progress):
        """
        更新漫画系列卷阅读进度
        """
        url = f"{self.BASE_URL}/v0/users/-/collections/{subject_id}"
        payload = {"vol_status": progress}
        try:
            response = self.r.patch(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"出现错误: {e}")
        return response.status_code == 204

    @slide_window_rate_limiter()
    def get_subject_thumbnail(self, subject_metadata, image_size):
        """
        获取漫画封面

        image_size可选值:
        large, common, medium,small, grid
        """
        try:
            if subject_metadata["images"]:
                image = subject_metadata["images"][image_size]
            else:
                image = self.get_subject_metadata(subject_metadata["id"])["images"][
                    image_size
                ]
            thumbnail = self.r.get(image, **proxy_kwargs(image, self.proxy_settings)).content
        except Exception as e:
            logger.error(f"出现错误: {e}")
            return []
        files = {"file": (subject_metadata["name"], thumbnail)}
        return files


class BangumiArchiveDataSource(DataSource):
    """
    离线数据源类
    """

    def __init__(self, local_archive_folder):
        from bangumi_archive.sqlite_store import ArchiveStore
        self.store = ArchiveStore(local_archive_folder or "./archivedata/")

    def _get_metadata_from_archive(self, subject_id):
        from tools.native_core import archive_request
        result = archive_request("get", self.store.folder, id=int(subject_id))
        if result is not None:
            return result
        return self.store.get(subject_id)

    # 将10s+的全文件扫描性能提升到1s左右
    def _get_search_results_from_archive(self, query):
        from tools.native_core import archive_request
        from bangumi_archive.sqlite_store import normalize
        result = archive_request("search", self.store.folder, query=normalize(query))
        if result is not None:
            return result
        return self.store.search(query)

    def search_subjects(self, query, threshold=80, is_novel=False):
        """
        离线数据源搜索条目
        """
        results = self._get_search_results_from_archive(query)
        return resort_search_list(
            query=query, results=results, threshold=threshold, is_novel=is_novel
        )

    def get_subject_metadata(self, subject_id):
        """
        离线数据源获取条目元数据
        """
        return self._get_metadata_from_archive(subject_id)

    def get_related_subjects(self, subject_id):
        """
        离线数据源获取关联条目列表
        """
        from tools.native_core import archive_request
        result = archive_request("relations", self.store.folder, id=int(subject_id))
        if result is not None:
            return result
        return self.store.relations(subject_id)

    def update_reading_progress(self, subject_id, progress):
        """
        离线数据源更新阅读进度
        """
        NotImplementedError("离线数据源不支持更新阅读进度")
        return False

    def get_subject_thumbnail(self, subject_metadata, image_size):
        """
        离线数据源获取封面
        """
        NotImplementedError("离线数据源不支持获取封面")
        return {}


class BangumiDataSourceFactory:
    """
    数据源工厂类
    """

    @staticmethod
    def create(config):
        online = BangumiApiDataSource(config.get("access_token"), config.get("proxy_url", ""))

        if config.get("use_local_archive", False):
            from bangumi_archive.sqlite_store import ensure_index_background
            ensure_index_background(config.get("local_archive_folder") or "./archivedata/")
            offline = BangumiArchiveDataSource(config.get("local_archive_folder"))
            return OfflineFirstDataSource(offline, online)

        return online


class OfflineFirstDataSource(DataSource):
    """Only search may use the online API; metadata/relations stay offline."""
    def __init__(self, offline, online):
        self.primary, self.secondary = offline, online
        if isinstance(online, BangumiApiDataSource):
            # Preserve the user's strict offline-detail policy even when
            # candidate discovery falls back to an online search.
            online.matching_detail_source = offline.get_subject_metadata

    def search_subjects(self, query, threshold=80, is_novel=False):
        local = self.primary.search_subjects(query, threshold, is_novel)
        if local:
            return local
        logger.info("离线搜索未命中，尝试 Bangumi 在线搜索：%s", query)
        hits = self.secondary.search_subjects(query, threshold, is_novel)
        results = []
        for hit in hits:
            detail = self.primary.get_subject_metadata(hit["id"])
            if detail:
                results.append(detail)
            else:
                logger.warning("在线搜索条目 %s 尚未进入离线库，跳过详情并等待归档更新", hit["id"])
        return resort_search_list(query, results, threshold, is_novel)

    def get_subject_metadata(self, subject_id):
        return self.primary.get_subject_metadata(subject_id)

    def get_related_subjects(self, subject_id):
        return self.primary.get_related_subjects(subject_id)

    def update_reading_progress(self, subject_id, progress):
        return False

    def get_subject_thumbnail(self, subject_metadata, image_size):
        # Official archives contain no images. Preserve existing Komga covers.
        return {}


class FallbackDataSource(DataSource):
    """
    备用数据源类，用于在主数据源失败时使用备用数据源
    """

    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary

    def _fallback_call(self, method_name, *args, **kwargs):
        # 优先调用 primary 数据源的方法
        result = getattr(self.primary, method_name)(*args, **kwargs)

        # 如果结果为空/False（根据业务逻辑判断），则尝试 secondary 数据源
        if not result:
            logger.debug(
                "主数据源: %s 失败，尝试备用数据源: %s",
                self.primary.__class__.__name__,
                self.secondary.__class__.__name__,
            )
            result = getattr(self.secondary, method_name)(*args, **kwargs)
        return result

    def search_subjects(self, query, threshold=80, is_novel=False):
        return self._fallback_call(
            "search_subjects", query, threshold=threshold, is_novel=is_novel
        )

    def get_subject_metadata(self, subject_id):
        return self._fallback_call("get_subject_metadata", subject_id)

    def get_related_subjects(self, subject_id):
        return self._fallback_call("get_related_subjects", subject_id)

    def update_reading_progress(self, subject_id, progress):
        self._fallback_call("update_reading_progress", subject_id, progress)

    def get_subject_thumbnail(self, subject_metadata, image_size):
        return self._fallback_call(
            "get_subject_thumbnail", subject_metadata, image_size
        )

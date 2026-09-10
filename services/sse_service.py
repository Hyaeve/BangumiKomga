import threading
from tools.log import logger

from config.config import KOMGA_LIBRARY_LIST
from core.refresh_metadata import refresh_metadata, get_series_metadata
from api.komga_sse_api import KomgaSseApi
from services.library_selection import is_configured_library
import threading

# FIXME: 监听了库内容变化, 但没有关注收藏集的内容变化


def _is_surveilled_library(library_id):
    """Return whether the event belongs to a configured scraping card."""
    return is_configured_library(KOMGA_LIBRARY_LIST, library_id)


def series_update_sse_handler(data):
    # TODO: 处理 series_id, library_id 或者 series_detail 的场景
    series_id = data["event_data"].get("seriesId") or data["event_data"].get("id")
    library_id = data["event_data"]["libraryId"]
    if not _is_surveilled_library(library_id):
        logger.info("libraryId: %s 未启用刮削匹配，跳过实时事件", library_id)
        return
    if not series_id:
        logger.info("SSE 事件缺少系列 ID，跳过实时刮削")
        return
    # 获取指定系列的详细信息
    series_detail = get_series_metadata([series_id])
    # 筛选有效的 SeriesChanged 事件
    if data["event_type"] == "SeriesChanged":
        # 判断 SeriesChanged 是否为CBL更改
        # 或者该系列并未匹配元数据
        if any(
            link["label"].lower() == "cbl"
            for link in series_detail[0]["metadata"]["links"]
        ):
            pass
        else:
            # 无视其他 SeriesChanged 事件
            return
    # 其他事件 RefreshEventType, 例如 SeriesAdded
    else:
        pass
    # 设置了 KOMGA_LIBRARY_LIST 且 library_id 不在 KOMGA_LIBRARY_LIST 中
    if _is_surveilled_library(library_id):
        refresh_metadata(series_detail)
    else:
        logger.info("libraryId: %s 未配置刮削卡片，跳过实时刮削", library_id)
    return


def sse_service():
    komga_api = KomgaSseApi()

    # 注册回调函数
    komga_api.register_series_update_callback(series_update_sse_handler)

    # 防止服务主线程退出
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        # 取消注册
        komga_api.unregister_series_update_callback(series_update_sse_handler)
        logger.warning("服务手动终止: 退出 BangumiKomga 服务")

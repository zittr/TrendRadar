# coding=utf-8

"""
热点新闻词频爬取与推送系统
功能介绍：
- 爬取指定网站的热点新闻数据
- 统计并筛选关键词频率，支持必需词和过滤词配置
- 结果保存为本地txt文件
- 支持飞书和Bark推送，并灵活控制推送开关
- 代理支持及请求重试保障稳定性
- 简化推送开关控制逻辑，易于理解和维护

依赖环境：
- requests
- pytz

安装方法：
pip install requests pytz
"""

import json
import time
import random
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Union
from pathlib import Path
import os
import requests
import pytz
import re

# ----------------------------- 配置区域 -----------------------------

CONFIG = {
    "FEISHU_SEPARATOR": "━━━━━━━━━━━━━━━━━━━",  # 飞书消息正文分割线
    "REQUEST_INTERVAL": 1000,  # 请求时间间隔，单位毫秒
    "FEISHU_REPORT_TYPE": "daily",  # 飞书报告类型，暂未影响逻辑
    "RANK_THRESHOLD": 5,  # 排名高亮阈值
    "USE_PROXY": False,  # 是否启用代理，开启请设置默认代理地址
    "DEFAULT_PROXY": "http://127.0.0.1:10086",  # 代理地址示例
    "FEISHU_WEBHOOK_URL": "",  # 飞书Webhook地址，推荐通过环境变量FEISHU_WEBHOOK_URL设置
    
    "BARK_SERVER_URL": "https://api.day.app/",  # Bark服务器地址
    "BARK_DEVICE_KEY": os.getenv("Bark_Key", ""),  # Bark设备Key，环境变量读取，推荐配置
    
    "FEISHU_ENABLE": True,  # 是否启用飞书推送
    "BARK_ENABLE": True,    # 是否启用Bark推送
    # 推送开关同时关闭时是否继续爬虫，True继续，False退出
    "CONTINUE_CRAWL_IF_PUSH_ALL_OFF": True,
}

# ----------------------------- 时间工具 -----------------------------


class TimeHelper:
    """时间相关工具"""

    @staticmethod
    def get_beijing_time() -> datetime:
        """获取当前北京时间（带时区）"""
        return datetime.now(pytz.timezone("Asia/Shanghai"))

    @staticmethod
    def format_date_folder() -> str:
        """格式化当前日期 YYYY年MM月DD日，适合文件夹命名"""
        return TimeHelper.get_beijing_time().strftime("%Y年%m月%d日")

    @staticmethod
    def format_time_filename() -> str:
        """格式化当前时间 HH时MM分，适合文件命名"""
        return TimeHelper.get_beijing_time().strftime("%H时%M分")


# --------------------------- 文件及目录 ----------------------------


class FileHelper:
    """文件操作工具"""

    @staticmethod
    def ensure_directory_exists(directory: str) -> None:
        """确保目录存在，如果不存在则创建"""
        Path(directory).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_output_path(subfolder: str, filename: str) -> str:
        """生成输出路径，结构为：output/日期目录/subfolder/filename"""
        date_folder = TimeHelper.format_date_folder()
        output_dir = Path("output") / date_folder / subfolder
        FileHelper.ensure_directory_exists(str(output_dir))
        return str(output_dir / filename)


# --------------------------- 数据爬取 ------------------------------


class DataFetcher:
    """负责从指定接口爬取新闻数据"""

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url

    def fetch_data(
        self,
        id_info: Union[str, Tuple[str, str]],
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[str], str, str]:
        """
        根据ID从接口获取JSON数据，支持重试机制。
        参数：
            - id_info: 单字符串ID或(ID, 别名)元组
        返回:
            - response文本或None，id值，别名
        """
        if isinstance(id_info, tuple):
            id_value, alias = id_info
        else:
            id_value = id_info
            alias = id_value

        url = f"https://newsnow.busiyi.world/api/s?id={id_value}&latest"

        proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

        retries = 0
        while retries <= max_retries:
            try:
                response = requests.get(url, proxies=proxies, headers=headers, timeout=10)
                response.raise_for_status()
                data_text = response.text
                data_json = json.loads(data_text)

                status = data_json.get("status", "未知")
                if status not in ["success", "cache"]:
                    raise ValueError(f"响应状态异常: {status}")

                status_info = "最新数据" if status == "success" else "缓存数据"
                print(f"获取 {id_value} 成功（{status_info}）")
                return data_text, id_value, alias

            except Exception as e:
                retries += 1
                if retries <= max_retries:
                    base_wait = random.uniform(min_retry_wait, max_retry_wait)
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait
                    print(f"请求 {id_value} 失败: {e}. {wait_time:.2f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"请求 {id_value} 失败: {e}")
                    return None, id_value, alias
        return None, id_value, alias

    def crawl_websites(
        self,
        ids_list: List[Union[str, Tuple[str, str]]],
        request_interval: int = CONFIG["REQUEST_INTERVAL"],
    ) -> Tuple[Dict, Dict, List]:
        """
        批量爬取多个ID对应的热点新闻数据。
        返回：
            - results: {id: {标题: {ranks: [排名], url: str, mobileUrl: str}}}
            - id_to_alias: {id: 别名}
            - failed_ids: 请求失败的ID列表
        """
        results = {}
        id_to_alias = {}
        failed_ids = []

        for i, id_info in enumerate(ids_list):
            if isinstance(id_info, tuple):
                id_value, alias = id_info
            else:
                id_value = id_info
                alias = id_value

            id_to_alias[id_value] = alias

            response, _, _ = self.fetch_data(id_info)

            if response:
                try:
                    data = json.loads(response)
                    results.setdefault(id_value, {})
                    for index, item in enumerate(data.get("items", []), start=1):
                        title = item.get("title", "").strip()
                        url = item.get("url", "")
                        mobile_url = item.get("mobileUrl", "")

                        if title in results[id_value]:
                            results[id_value][title]["ranks"].append(index)
                        else:
                            results[id_value][title] = {
                                "ranks": [index],
                                "url": url,
                                "mobileUrl": mobile_url,
                            }
                except Exception as e:
                    print(f"解析或处理 {id_value} 响应数据失败: {e}")
                    failed_ids.append(id_value)
            else:
                failed_ids.append(id_value)

            if i < len(ids_list) - 1:
                jitter = random.randint(-10, 20)
                actual_interval = max(50, request_interval + jitter)
                time.sleep(actual_interval / 1000)

        print(f"成功采集ID：{list(results.keys())}")
        print(f"失败采集ID：{failed_ids}")
        return results, id_to_alias, failed_ids


# --------------------------- 数据处理 ------------------------------


class DataProcessor:
    """处理和保存爬取到的热点新闻数据"""

    @staticmethod
    def save_titles_to_file(results: Dict, id_to_alias: Dict, failed_ids: List) -> str:
        """
        将结果保存为txt文件，格式清晰，包含排名、标题与链接。
        返回保存文件的完整路径。
        """
        file_path = FileHelper.get_output_path(
            "txt", f"{TimeHelper.format_time_filename()}.txt"
        )

        with open(file_path, "w", encoding="utf-8") as f:
            for id_value, titles_data in results.items():
                display_name = id_to_alias.get(id_value, id_value)
                f.write(f"{display_name}\n")

                sorted_titles = []
                for title, info in titles_data.items():
                    ranks = info.get("ranks", [])
                    url = info.get("url", "")
                    mobile_url = info.get("mobileUrl", "")
                    min_rank = min(ranks) if ranks else 99
                    sorted_titles.append((min_rank, title, url, mobile_url))

                sorted_titles.sort(key=lambda x: x[0])

                for rank, title, url, mobile_url in sorted_titles:
                    line = f"{rank}. {title}"
                    if url:
                        line += f" [URL:{url}]"
                    if mobile_url:
                        line += f" [MOBILE:{mobile_url}]"
                    f.write(line + "\n")

                f.write("\n")

            if failed_ids:
                f.write("==== 以下ID请求失败 ====\n")
                for fail_id in failed_ids:
                    fail_alias = id_to_alias.get(fail_id, fail_id)
                    f.write(f"{fail_alias} (ID: {fail_id})\n")

        print(f"热点新闻标题已保存到文件：{file_path}")
        return file_path


# ------------------------- 词频统计 -------------------------------


class StatisticsCalculator:
    """关键词频率统计与标题筛选"""

    @staticmethod
    def _matches_word_groups(
        title: str, word_groups: List[Dict], filter_words: List[str]
    ) -> bool:
        """
        判断标题是否符合词组必需词及不包含过滤词规则。
        优先排除包含过滤词的标题。
        """
        title_lower = title.lower()
        for filter_word in filter_words:
            if filter_word.lower() in title_lower:
                return False

        for group in word_groups:
            required_words = group.get("required", [])
            normal_words = group.get("normal", [])

            # 检查必需词全部存在
            if required_words and not all(req.lower() in title_lower for req in required_words):
                continue

            # 检查普通词至少一个存在
            if normal_words and any(norm.lower() in title_lower for norm in normal_words):
                return True

        return False

    @staticmethod
    def count_word_frequency(
        results: Dict,
        word_groups: List[Dict],
        filter_words: List[str],
        id_to_alias: Dict,
        rank_threshold: int = CONFIG["RANK_THRESHOLD"],
    ) -> List[Dict]:
        """
        统计所有标题符合词组规则的出现频率，返回排序后的统计列表。
        """
        word_stats = {}

        for group in word_groups:
            key = group["group_key"]
            word_stats[key] = {"count": 0, "titles": []}

        for source_id, titles_data in results.items():
            source_alias = id_to_alias.get(source_id, source_id)
            for title, info in titles_data.items():
                # 过滤不符规则的标题
                if not StatisticsCalculator._matches_word_groups(title, word_groups, filter_words):
                    continue
                ranks = info.get("ranks", [])
                url = info.get("url", "")
                mobile_url = info.get("mobileUrl", "")

                # 找到第一个匹配的词组，计入统计
                for group in word_groups:
                    required_words = group.get("required", [])
                    normal_words = group.get("normal", [])
                    key = group["group_key"]

                    title_lower = title.lower()
                    if required_words and not all(req.lower() in title_lower for req in required_words):
                        continue
                    if normal_words and not any(norm.lower() in title_lower for norm in normal_words):
                        continue

                    word_stats[key]["count"] += 1
                    word_stats[key]["titles"].append({
                        "title": title,
                        "source_alias": source_alias,
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                        "rank_threshold": rank_threshold,
                    })
                    break  # 一个标题只计入第一个匹配组

        stats_list = []
        for k, v in word_stats.items():
            stats_list.append({
                "word": k,
                "count": v["count"],
                "titles": v["titles"],
            })

        stats_list.sort(key=lambda x: x["count"], reverse=True)  # 按出现次数降序
        return stats_list

    @staticmethod
    def format_rank_html(ranks: List[int], rank_threshold: int = 5) -> str:
        """
        格式化排名显示，阈值内用红色粗体高亮。
        """
        if not ranks:
            return ""

        unique_ranks = sorted(set(ranks))
        min_rank = unique_ranks[0]
        max_rank = unique_ranks[-1]

        if min_rank <= rank_threshold:
            if min_rank == max_rank:
                return f"<font color='red'><strong>[{min_rank}]</strong></font>"
            else:
                return f"<font color='red'><strong>[{min_rank} - {max_rank}]</strong></font>"
        else:
            if min_rank == max_rank:
                return f"[{min_rank}]"
            else:
                return f"[{min_rank} - {max_rank}]"


# ---------------------------- 报告生成和推送 -------------------------


class ReportGenerator:
    """将统计结果生成人类可读文本，并推送到飞书和Bark"""

    @staticmethod
    def _render_feishu_content(stats: List[Dict]) -> str:
        """
        生成飞书纯文本报告内容
        """
        lines = []
        for stat in stats:
            lines.append(f"{stat['word']} (出现次数: {stat['count']})")
            for title_record in stat["titles"]:
                rank_html = StatisticsCalculator.format_rank_html(
                    title_record["ranks"], title_record["rank_threshold"]
                )
                lines.append(f"{rank_html} {title_record['title']} — 来源：{title_record['source_alias']}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def send_to_feishu(text: str) -> bool:
        """
        通过飞书Webhook发送文本消息，返回是否成功
        """
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])
        if not webhook_url:
            print("飞书Webhook未配置，跳过发送。")
            return False

        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"msg_type": "text", "content": {"text": text}}

        try:
            response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                print("飞书推送成功")
                return True
            else:
                print(f"飞书推送失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"飞书推送异常: {e}")
        return False

    @staticmethod
    def send_to_bark(stats: List[Dict], report_type: str = "热点新闻推送") -> bool:
        """
        给Bark服务推送简要消息，标题使用第一个关键词，消息正文转换自飞书内容。
        """
        if not CONFIG.get("BARK_ENABLE", False):
            print("Bark推送已关闭，跳过发送。")
            return False

        device_key = CONFIG.get("BARK_DEVICE_KEY", "")
        server_url = CONFIG.get("BARK_SERVER_URL", "https://api.day.app")

        if not device_key:
            print("Bark设备Key未设置，跳过推送。")
            return False

        def html_to_plain(text: str) -> str:
            text = re.sub(r"<.*?>", "", text)
            return text.strip()

        body = ReportGenerator._render_feishu_content(stats)
        bark_body = html_to_plain(body)
        first_word = stats[0]["word"] if stats else "热点新闻"
        now_str = TimeHelper.get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

        title = f"{first_word} - {report_type}"
        subtitle = f"更新时间：{now_str}"
        group = "热点新闻"

        params = {
            "title": title,
            "body": bark_body,
            "subtitle": subtitle,
            "group": group,
        }
        url = f"{server_url.rstrip('/')}/{device_key}"

        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                print(f"Bark推送成功 [{report_type}]")
                return True
            else:
                print(f"Bark推送失败，状态码: {resp.status_code}")
        except Exception as e:
            print(f"Bark推送异常: {e}")
        return False


# -------------------------- 主逻辑入口 ------------------------------


class NewsAnalyzer:
    """
    集成爬取、处理、统计、保存及推送流程
    """

    def __init__(self):
        proxy = CONFIG["DEFAULT_PROXY"] if CONFIG["USE_PROXY"] else None
        self.fetcher = DataFetcher(proxy_url=proxy)

    def run(self):
        print(f"当前北京时间: {TimeHelper.get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')}")

        feishu_on = CONFIG.get("FEISHU_ENABLE", False)
        bark_on = CONFIG.get("BARK_ENABLE", False)
        continue_crawl = CONFIG.get("CONTINUE_CRAWL_IF_PUSH_ALL_OFF", True)

        if not feishu_on and not bark_on:
            if continue_crawl:
                print("推送开关均关闭，但配置允许继续爬虫，继续执行。")
            else:
                print("推送开关均关闭，且配置不允许继续爬虫，程序结束。")
                return

        # 飞书Webhook地址获取及提示（不退出）
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])
        if not webhook_url and feishu_on:
            print("警告：飞书Webhook地址未设置，飞书推送将跳过。")

        # 示例爬取的ID列表（请按需替换）
        ids_to_crawl = [
            "saijia",
            ("soccer", "足球频道"),
            # 可以添加更多ID或(ID, "别名")元组
        ]

        # 1. 爬取数据
        results, id_to_alias, failed_ids = self.fetcher.crawl_websites(ids_to_crawl)

        # 2. 保存爬取数据到文件
        DataProcessor.save_titles_to_file(results, id_to_alias, failed_ids)

        # 3. 词频规则配置（示例）
        example_word_groups = [
            {"required": [], "normal": ["世界杯"], "group_key": "世界杯"},
            {"required": ["足球"], "normal": ["赛事", "比赛"], "group_key": "足球赛事"},
        ]
        example_filter_words = ["虚假"]  # 示例过滤词（标题中包含则剔除）

        # 4. 统计词频
        stats = StatisticsCalculator.count_word_frequency(
            results, example_word_groups, example_filter_words, id_to_alias
        )

        if not stats:
            print("无符合词频统计的标题，推送内容为空，结束程序。")
            return

        # 5. 构造飞书推送文本并打印（便于调试）
        feishu_text = ReportGenerator._render_feishu_content(stats)
        print("飞书推送内容预览：\n", feishu_text)

        # 6. 执行推送（根据开关）
        if feishu_on and webhook_url:
            ReportGenerator.send_to_feishu(feishu_text)
        else:
            print("飞书推送关闭或未配置Webhook，跳过飞书推送。")

        if bark_on:
            ReportGenerator.send_to_bark(stats)
        else:
            print("Bark推送关闭，跳过Bark推送。")


if __name__ == "__main__":
    analyzer = NewsAnalyzer()
    analyzer.run()

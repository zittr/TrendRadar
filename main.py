# coding=utf-8

import json  # 处理json数据
import time  # 时间相关功能
import random  # 随机数生成
from datetime import datetime  # 日期时间处理
import webbrowser  # 打开网页
from typing import Dict, List, Tuple, Optional, Union  # 类型提示
from pathlib import Path  # 路径处理
import os  # 操作系统接口

import requests  # HTTP请求
import pytz  # 时区处理


CONFIG = {
    "FEISHU_SEPARATOR": "━━━━━━━━━━━━━━━━━━━",  # 飞书消息分割线，注意，其它类型的分割线可能会被飞书过滤而不显示
    "REQUEST_INTERVAL": 1000,  # 请求间隔(毫秒)
    "FEISHU_REPORT_TYPE": "daily",  # 飞书报告类型: "current"|"daily"|"both"
    "RANK_THRESHOLD": 5,  # 排名高亮阈值
    "USE_PROXY": True,  # 是否启用代理
    "DEFAULT_PROXY": "http://127.0.0.1:10086",  # 代理地址备用
    "CONTINUE_WITHOUT_FEISHU": True,  # 在无飞书Webhook时，是否继续爬虫
    "FEISHU_WEBHOOK_URL": "",  # 飞书机器人的 webhook URL，推荐通过环境变量或GitHub Secrets设置

    # 新增推送控制相关配置
    "FEISHU_ENABLE": True,  # 飞书推送开关，True启用，False关闭
    "BARK_ENABLE": True,    # Bark推送开关，True启用，False关闭
    "BARK_SERVER_URL": "https://api.day.app",  # Bark服务器地址
    "BARK_DEVICE_KEY": os.getenv("Bark_Key", ""),  # Bark设备Key，从环境变量读取
    "CONTINUE_CRAWL_IF_PUSH_ALL_OFF": True,  # 两个推送均关闭时是否继续爬虫，True执行，False退出
}


class TimeHelper:
    """时间处理工具"""

    @staticmethod
    def get_beijing_time() -> datetime:
        return datetime.now(pytz.timezone("Asia/Shanghai"))  # 获取当前北京时间

    @staticmethod
    def format_date_folder() -> str:
        return TimeHelper.get_beijing_time().strftime("%Y年%m月%d日")  # 格式化当前日期，用于文件夹名

    @staticmethod
    def format_time_filename() -> str:
        return TimeHelper.get_beijing_time().strftime("%H时%M分")  # 格式化时间，用于文件名


class FileHelper:
    """文件操作工具"""

    @staticmethod
    def ensure_directory_exists(directory: str) -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)  # 确保目录存在，不存在则创建多层目录

    @staticmethod
    def get_output_path(subfolder: str, filename: str) -> str:
        date_folder = TimeHelper.format_date_folder()  # 获取日期文件夹名
        output_dir = Path("output") / date_folder / subfolder  # 构造完整目录
        FileHelper.ensure_directory_exists(str(output_dir))  # 确保目录存在
        return str(output_dir / filename)  # 返回完整文件路径


class DataFetcher:
    """数据获取器"""

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url  # 代理地址，None表示不使用代理

    def fetch_data(
        self,
        id_info: Union[str, Tuple[str, str]],
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[str], str, str]:
        """获取指定ID数据，支持重试"""
        if isinstance(id_info, tuple):
            id_value, alias = id_info
        else:
            id_value = id_info
            alias = id_value

        url = f"https://newsnow.busiyi.world/api/s?id={id_value}&latest"

        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}  # 设置http/https代理

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

        retries = 0
        while retries <= max_retries:
            try:
                response = requests.get(url, proxies=proxies, headers=headers, timeout=10)  # 发送请求
                response.raise_for_status()  # 非200抛异常

                data_text = response.text
                data_json = json.loads(data_text)  # 解析json

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
        """爬取多个网站数据"""
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
                    results[id_value] = {}
                    for index, item in enumerate(data.get("items", []), 1):
                        title = item["title"]
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
                except json.JSONDecodeError:
                    print(f"解析 {id_value} 响应失败")
                    failed_ids.append(id_value)
                except Exception as e:
                    print(f"处理 {id_value} 数据出错: {e}")
                    failed_ids.append(id_value)
            else:
                failed_ids.append(id_value)

            if i < len(ids_list) - 1:
                actual_interval = request_interval + random.randint(-10, 20)
                actual_interval = max(50, actual_interval)
                time.sleep(actual_interval / 1000)

        print(f"成功: {list(results.keys())}, 失败: {failed_ids}")
        return results, id_to_alias, failed_ids


class DataProcessor:
    """数据处理器"""

    @staticmethod
    def detect_latest_new_titles(id_to_alias: Dict) -> Dict:
        """检测当日最新批次的新增标题"""
        date_folder = TimeHelper.format_date_folder()
        txt_dir = Path("output") / date_folder / "txt"

        if not txt_dir.exists():
            return {}

        files = sorted([f for f in txt_dir.iterdir() if f.suffix == ".txt"])
        if len(files) < 2:
            if len(files) == 1:
                return DataProcessor._parse_file_titles(files[0])
            return {}

        latest_file = files[-1]
        latest_titles = DataProcessor._parse_file_titles(latest_file)

        # 汇总历史标题
        historical_titles = {}
        for file_path in files[:-1]:
            historical_data = DataProcessor._parse_file_titles(file_path)
            for source_name, titles_data in historical_data.items():
                if source_name not in historical_titles:
                    historical_titles[source_name] = set()
                for title in titles_data.keys():
                    historical_titles[source_name].add(title)

        # 找出新增标题
        new_titles = {}
        for source_name, latest_source_titles in latest_titles.items():
            historical_set = historical_titles.get(source_name, set())
            source_new_titles = {}

            for title, title_data in latest_source_titles.items():
                if title not in historical_set:
                    source_new_titles[title] = title_data

            if source_new_titles:
                source_id = None
                for id_val, alias in id_to_alias.items():
                    if alias == source_name:
                        source_id = id_val
                        break
                if source_id:
                    new_titles[source_id] = source_new_titles

        return new_titles

    @staticmethod
    def _parse_file_titles(file_path: Path) -> Dict:
        """解析单个txt文件的标题数据"""
        titles_by_source = {}

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            sections = content.split("\n\n")

            for section in sections:
                if not section.strip() or "==== 以下ID请求失败 ====" in section:
                    continue

                lines = section.strip().split("\n")
                if len(lines) < 2:
                    continue

                source_name = lines[0].strip()
                titles_by_source[source_name] = {}

                for line in lines[1:]:
                    if line.strip():
                        try:
                            title_part = line.strip()
                            rank = None

                            # 提取排名
                            if (
                                ". " in title_part
                                and title_part.split(". ")[0].isdigit()
                            ):
                                rank_str, title_part = title_part.split(". ", 1)
                                rank = int(rank_str)

                            # 提取MOBILE URL
                            mobile_url = ""
                            if " [MOBILE:" in title_part:
                                title_part, mobile_part = title_part.rsplit(
                                    " [MOBILE:", 1
                                )
                                if mobile_part.endswith("]"):
                                    mobile_url = mobile_part[:-1]

                            # 提取URL
                            url = ""
                            if " [URL:" in title_part:
                                title_part, url_part = title_part.rsplit(" [URL:", 1)
                                if url_part.endswith("]"):
                                    url = url_part[:-1]

                            title = title_part.strip()
                            ranks = [rank] if rank is not None else [1]

                            titles_by_source[source_name][title] = {
                                "ranks": ranks,
                                "url": url,
                                "mobileUrl": mobile_url,
                            }

                        except Exception as e:
                            print(f"解析标题行出错: {line}, 错误: {e}")

        return titles_by_source

    @staticmethod
    def save_titles_to_file(results: Dict, id_to_alias: Dict, failed_ids: List) -> str:
        """保存标题到文件"""
        file_path = FileHelper.get_output_path(
            "txt", f"{TimeHelper.format_time_filename()}.txt"
        )

        with open(file_path, "w", encoding="utf-8") as f:
            for id_value, title_data in results.items():
                display_name = id_to_alias.get(id_value, id_value)
                f.write(f"{display_name}\n")

                # 按排名排序标题
                sorted_titles = []
                for title, info in title_data.items():
                    if isinstance(info, dict):
                        ranks = info.get("ranks", [])
                        url = info.get("url", "")
                        mobile_url = info.get("mobileUrl", "")
                    else:
                        ranks = info if isinstance(info, list) else []
                        url = ""
                        mobile_url = ""

                    rank = ranks[0] if ranks else 1
                    sorted_titles.append((rank, title, url, mobile_url))

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
                for id_value in failed_ids:
                    display_name = id_to_alias.get(id_value, id_value)
                    f.write(f"{display_name} (ID: {id_value})\n")

        return file_path

    @staticmethod
    def load_frequency_words(
        frequency_file: str = "frequency_words.txt",
    ) -> Tuple[List[Dict], List[str]]:
        """加载频率词配置"""
        frequency_path = Path(frequency_file)
        if not frequency_path.exists():
            print(f"频率词文件 {frequency_file} 不存在")
            return [], []

        with open(frequency_path, "r", encoding="utf-8") as f:
            content = f.read()

        word_groups = [
            group.strip() for group in content.split("\n\n") if group.strip()
        ]

        processed_groups = []
        filter_words = []

        for group in word_groups:
            words = [word.strip() for word in group.split("\n") if word.strip()]

            group_required_words = []
            group_normal_words = []
            group_filter_words = []

            for word in words:
                if word.startswith("!"):
                    filter_words.append(word[1:])
                    group_filter_words.append(word[1:])
                elif word.startswith("+"):
                    group_required_words.append(word[1:])
                else:
                    group_normal_words.append(word)

            if group_required_words or group_normal_words:
                if group_normal_words:
                    group_key = " ".join(group_normal_words)
                else:
                    group_key = " ".join(group_required_words)

                processed_groups.append(
                    {
                        "required": group_required_words,
                        "normal": group_normal_words,
                        "group_key": group_key,
                    }
                )

        return processed_groups, filter_words

    @staticmethod
    def read_all_today_titles() -> Tuple[Dict, Dict, Dict]:
        """读取当天所有标题文件"""
        date_folder = TimeHelper.format_date_folder()
        txt_dir = Path("output") / date_folder / "txt"

        if not txt_dir.exists():
            return {}, {}, {}

        all_results = {}
        id_to_alias = {}
        title_info = {}

        files = sorted([f for f in txt_dir.iterdir() if f.suffix == ".txt"])

        for file_path in files:
            time_info = file_path.stem

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

                sections = content.split("\n\n")
                for section in sections:
                    if not section.strip() or "==== 以下ID请求失败 ====" in section:
                        continue

                    lines = section.strip().split("\n")
                    if len(lines) < 2:
                        continue

                    source_name = lines[0].strip()
                    title_data = {}

                    for line in lines[1:]:
                        if line.strip():
                            try:
                                rank = None
                                title_part = line.strip()

                                # 提取行首的排名数字
                                if (
                                    ". " in title_part
                                    and title_part.split(". ")[0].isdigit()
                                ):
                                    parts = title_part.split(". ", 1)
                                    rank = int(parts[0])
                                    title_part = parts[1]

                                # 提取 MOBILE URL
                                mobile_url = ""
                                if " [MOBILE:" in title_part:
                                    title_part, mobile_part = title_part.rsplit(
                                        " [MOBILE:", 1
                                    )
                                    if mobile_part.endswith("]"):
                                        mobile_url = mobile_part[:-1]

                                # 提取 URL
                                url = ""
                                if " [URL:" in title_part:
                                    title_part, url_part = title_part.rsplit(
                                        " [URL:", 1
                                    )
                                    if url_part.endswith("]"):
                                        url = url_part[:-1]

                                title = title_part.strip()
                                ranks = [rank] if rank is not None else [1]

                                title_data[title] = {
                                    "ranks": ranks,
                                    "url": url,
                                    "mobileUrl": mobile_url,
                                }

                            except Exception as e:
                                print(f"解析标题行出错: {line}, 错误: {e}")

                    DataProcessor._process_source_data(
                        source_name,
                        title_data,
                        time_info,
                        all_results,
                        title_info,
                        id_to_alias,
                    )

        # 转换为ID格式
        id_results = {}
        id_title_info = {}
        for name, titles in all_results.items():
            for id_value, alias in id_to_alias.items():
                if alias == name:
                    id_results[id_value] = titles
                    id_title_info[id_value] = title_info[name]
                    break

        return id_results, id_to_alias, id_title_info

    @staticmethod
    def _process_source_data(
        source_name: str,
        title_data: Dict,
        time_info: str,
        all_results: Dict,
        title_info: Dict,
        id_to_alias: Dict,
    ) -> None:
        """处理来源数据，合并重复标题"""
        if source_name not in all_results:
            all_results[source_name] = title_data

            if source_name not in title_info:
                title_info[source_name] = {}

            for title, data in title_data.items():
                ranks = data.get("ranks", [])
                url = data.get("url", "")
                mobile_url = data.get("mobileUrl", "")

                title_info[source_name][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }

            reversed_id = source_name.lower().replace(" ", "-")
            id_to_alias[reversed_id] = source_name
        else:
            for title, data in title_data.items():
                ranks = data.get("ranks", [])
                url = data.get("url", "")
                mobile_url = data.get("mobileUrl", "")

                if title not in all_results[source_name]:
                    all_results[source_name][title] = {
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                    }
                    title_info[source_name][title] = {
                        "first_time": time_info,
                        "last_time": time_info,
                        "count": 1,
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                    }
                else:
                    existing_data = all_results[source_name][title]
                    existing_ranks = existing_data.get("ranks", [])
                    existing_url = existing_data.get("url", "")
                    existing_mobile_url = existing_data.get("mobileUrl", "")

                    merged_ranks = existing_ranks.copy()
                    for rank in ranks:
                        if rank not in merged_ranks:
                            merged_ranks.append(rank)

                    all_results[source_name][title] = {
                        "ranks": merged_ranks,
                        "url": existing_url or url,
                        "mobileUrl": existing_mobile_url or mobile_url,
                    }

                    title_info[source_name][title]["last_time"] = time_info
                    title_info[source_name][title]["ranks"] = merged_ranks
                    title_info[source_name][title]["count"] += 1
                    if not title_info[source_name][title].get("url"):
                        title_info[source_name][title]["url"] = url
                    if not title_info[source_name][title].get("mobileUrl"):
                        title_info[source_name][title]["mobileUrl"] = mobile_url


class StatisticsCalculator:
    """统计计算器"""

    @staticmethod
    def _matches_word_groups(
        title: str, word_groups: List[Dict], filter_words: List[str]
    ) -> bool:
        """检查标题是否匹配词组规则"""
        title_lower = title.lower()

        # 过滤词检查
        if any(filter_word.lower() in title_lower for filter_word in filter_words):
            return False

        # 词组匹配检查
        for group in word_groups:
            required_words = group["required"]
            normal_words = group["normal"]

            # 必须词检查
            if required_words:
                all_required_present = all(
                    req_word.lower() in title_lower for req_word in required_words
                )
                if not all_required_present:
                    continue

            # 普通词检查
            if normal_words:
                any_normal_present = any(
                    normal_word.lower() in title_lower for normal_word in normal_words
                )
                if not any_normal_present:
                    continue

            return True

        return False

    @staticmethod
    def count_word_frequency(
        results: Dict,
        word_groups: List[Dict],
        filter_words: List[str],
        id_to_alias: Dict,
        title_info: Optional[Dict] = None,
        rank_threshold: int = CONFIG["RANK_THRESHOLD"],
        new_titles: Optional[Dict] = None,
    ) -> Tuple[List[Dict], int]:
        """统计词频，支持必须词、频率词、过滤词，并标记新增标题"""
        word_stats = {}
        total_titles = 0
        processed_titles = {}

        if title_info is None:
            title_info = {}
        if new_titles is None:
            new_titles = {}

        for group in word_groups:
            group_key = group["group_key"]
            word_stats[group_key] = {"count": 0, "titles": {}}

        for source_id, titles_data in results.items():
            total_titles += len(titles_data)

            if source_id not in processed_titles:
                processed_titles[source_id] = {}

            for title, title_data in titles_data.items():
                if title in processed_titles.get(source_id, {}):
                    continue

                # 使用统一的匹配逻辑
                if not StatisticsCalculator._matches_word_groups(
                    title, word_groups, filter_words
                ):
                    continue

                source_ranks = title_data.get("ranks", [])
                source_url = title_data.get("url", "")
                source_mobile_url = title_data.get("mobileUrl", "")

                # 找到匹配的词组
                title_lower = title.lower()
                for group in word_groups:
                    required_words = group["required"]
                    normal_words = group["normal"]

                    # 再次检查匹配
                    if required_words:
                        all_required_present = all(
                            req_word.lower() in title_lower
                            for req_word in required_words
                        )
                        if not all_required_present:
                            continue

                    if normal_words:
                        any_normal_present = any(
                            normal_word.lower() in title_lower
                            for normal_word in normal_words
                        )
                        if not any_normal_present:
                            continue

                    group_key = group["group_key"]
                    word_stats[group_key]["count"] += 1
                    if source_id not in word_stats[group_key]["titles"]:
                        word_stats[group_key]["titles"][source_id] = []

                    first_time = ""
                    last_time = ""
                    count_info = 1
                    ranks = source_ranks if source_ranks else []
                    url = source_url
                    mobile_url = source_mobile_url

                    if (
                        title_info
                        and source_id in title_info
                        and title in title_info[source_id]
                    ):
                        info = title_info[source_id][title]
                        first_time = info.get("first_time", "")
                        last_time = info.get("last_time", "")
                        count_info = info.get("count", 1)
                        if "ranks" in info and info["ranks"]:
                            ranks = info["ranks"]
                        url = info.get("url", source_url)
                        mobile_url = info.get("mobileUrl", source_mobile_url)

                    if not ranks:
                        ranks = [99]

                    time_display = StatisticsCalculator._format_time_display(
                        first_time, last_time
                    )

                    source_alias = id_to_alias.get(source_id, source_id)
                    is_new = source_id in new_titles and title in new_titles[source_id]

                    word_stats[group_key]["titles"][source_id].append(
                        {
                            "title": title,
                            "source_alias": source_alias,
                            "first_time": first_time,
                            "last_time": last_time,
                            "time_display": time_display,
                            "count": count_info,
                            "ranks": ranks,
                            "rank_threshold": rank_threshold,
                            "url": url,
                            "mobileUrl": mobile_url,
                            "is_new": is_new,
                        }
                    )

                    if source_id not in processed_titles:
                        processed_titles[source_id] = {}
                    processed_titles[source_id][title] = True
                    break

        stats = []
        for group_key, data in word_stats.items():
            all_titles = []
            for source_id, title_list in data["titles"].items():
                all_titles.extend(title_list)

            stats.append(
                {
                    "word": group_key,
                    "count": data["count"],
                    "titles": all_titles,
                    "percentage": (
                        round(data["count"] / total_titles * 100, 2)
                        if total_titles > 0
                        else 0
                    ),
                }
            )

        stats.sort(key=lambda x: x["count"], reverse=True)
        return stats, total_titles

    @staticmethod
    def _format_rank_base(
        ranks: List[int], rank_threshold: int = 5, format_type: str = "html"
    ) -> str:
        """基础排名格式化方法"""
        if not ranks:
            return ""

        unique_ranks = sorted(set(ranks))
        min_rank = unique_ranks[0]
        max_rank = unique_ranks[-1]

        # 根据格式类型选择不同的标记方式
        if format_type == "html":
            highlight_start = "<font color='red'><strong>"
            highlight_end = "</strong></font>"
        else:  # feishu
            highlight_start = "<font color='red'>**"
            highlight_end = "**</font>"

        # 格式化排名显示
        if min_rank <= rank_threshold:
            if min_rank == max_rank:
                return f"{highlight_start}[{min_rank}]{highlight_end}"
            else:
                return f"{highlight_start}[{min_rank} - {max_rank}]{highlight_end}"
        else:
            if min_rank == max_rank:
                return f"[{min_rank}]"
            else:
                return f"[{min_rank} - {max_rank}]"

    @staticmethod
    def _format_rank_for_html(ranks: List[int], rank_threshold: int = 5) -> str:
        """格式化HTML排名显示"""
        return StatisticsCalculator._format_rank_base(ranks, rank_threshold, "html")

    @staticmethod
    def _format_rank_for_feishu(ranks: List[int], rank_threshold: int = 5) -> str:
        """格式化飞书排名显示"""
        return StatisticsCalculator._format_rank_base(ranks, rank_threshold, "feishu")

    @staticmethod
    def _format_time_display(first_time: str, last_time: str) -> str:
        """格式化时间显示"""
        if not first_time:
            return ""
        if first_time == last_time or not last_time:
            return first_time
        else:
            return f"[{first_time} ~ {last_time}]"


class ReportGenerator:
    """报告生成器"""

    @staticmethod
    def generate_html_report(
        stats: List[Dict],
        total_titles: int,
        failed_ids: Optional[List] = None,
        is_daily: bool = False,
        new_titles: Optional[Dict] = None,
        id_to_alias: Optional[Dict] = None,
    ) -> str:
        """生成HTML报告"""
        if is_daily:
            filename = "当日统计.html"
        else:
            filename = f"{TimeHelper.format_time_filename()}.html"

        file_path = FileHelper.get_output_path("html", filename)

        # 数据处理层
        report_data = ReportGenerator._prepare_report_data(
            stats, failed_ids, new_titles, id_to_alias
        )

        # 渲染层
        html_content = ReportGenerator._render_html_content(
            report_data, total_titles, is_daily
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        if is_daily:
            root_file_path = Path("index.html")
            with open(root_file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

        return file_path

    @staticmethod
    def _prepare_report_data(
        stats: List[Dict],
        failed_ids: Optional[List] = None,
        new_titles: Optional[Dict] = None,
        id_to_alias: Optional[Dict] = None,
    ) -> Dict:
        """准备报告数据"""
        filtered_new_titles = {}
        if new_titles and id_to_alias:
            word_groups, filter_words = DataProcessor.load_frequency_words()
            for source_id, titles_data in new_titles.items():
                filtered_titles = ReportGenerator._apply_frequency_filter(
                    titles_data, word_groups, filter_words
                )
                if filtered_titles:
                    filtered_new_titles[source_id] = filtered_titles

        processed_stats = []
        for stat in stats:
            if stat["count"] <= 0:
                continue

            processed_titles = []
            for title_data in stat["titles"]:
                processed_title = {
                    "title": title_data["title"],
                    "source_alias": title_data["source_alias"],
                    "time_display": title_data["time_display"],
                    "count": title_data["count"],
                    "ranks": title_data["ranks"],
                    "rank_threshold": title_data["rank_threshold"],
                    "url": title_data.get("url", ""),
                    "mobile_url": title_data.get("mobileUrl", ""),
                    "is_new": title_data.get("is_new", False),
                }
                processed_titles.append(processed_title)

            processed_stats.append(
                {
                    "word": stat["word"],
                    "count": stat["count"],
                    "percentage": stat.get("percentage", 0),
                    "titles": processed_titles,
                }
            )

        processed_new_titles = []
        if filtered_new_titles and id_to_alias:
            for source_id, titles_data in filtered_new_titles.items():
                source_alias = id_to_alias.get(source_id, source_id)
                source_titles = []

                for title, title_data in titles_data.items():
                    url, mobile_url, ranks = ReportGenerator._extract_title_data_fields(
                        title_data
                    )

                    processed_title = {
                        "title": title,
                        "source_alias": source_alias,
                        "time_display": "",
                        "count": 1,
                        "ranks": ranks,
                        "rank_threshold": CONFIG["RANK_THRESHOLD"],
                        "url": url,
                        "mobile_url": mobile_url,
                        "is_new": True,
                    }
                    source_titles.append(processed_title)

                if source_titles:
                    processed_new_titles.append(
                        {
                            "source_id": source_id,
                            "source_alias": source_alias,
                            "titles": source_titles,
                        }
                    )

        return {
            "stats": processed_stats,
            "new_titles": processed_new_titles,
            "failed_ids": failed_ids or [],
            "total_new_count": sum(
                len(source["titles"]) for source in processed_new_titles
            ),
        }

    @staticmethod
    def _extract_title_data_fields(title_data) -> Tuple[str, str, List[int]]:
        """提取标题数据的通用字段"""
        url = title_data.get("url", "")
        mobile_url = title_data.get("mobileUrl", "")
        ranks = title_data.get("ranks", [])

        return url, mobile_url, ranks

    @staticmethod
    def _apply_frequency_filter(
        titles_data: Dict, word_groups: List[Dict], filter_words: List[str]
    ) -> Dict:
        """应用频率词过滤逻辑"""
        filtered_titles = {}

        for title, title_data in titles_data.items():
            if StatisticsCalculator._matches_word_groups(
                title, word_groups, filter_words
            ):
                filtered_titles[title] = title_data

        return filtered_titles

    @staticmethod
    def _html_escape(text: str) -> str:
        """HTML转义"""
        if not isinstance(text, str):
            text = str(text)

        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    @staticmethod
    def _format_title_html(title_data: Dict) -> str:
        """格式化HTML标题显示"""
        rank_display = StatisticsCalculator._format_rank_for_html(
            title_data["ranks"], title_data["rank_threshold"]
        )

        link_url = title_data["mobile_url"] or title_data["url"]
        escaped_title = ReportGenerator._html_escape(title_data["title"])
        escaped_source_alias = ReportGenerator._html_escape(title_data["source_alias"])

        if link_url:
            escaped_url = ReportGenerator._html_escape(link_url)
            formatted_title = f'[{escaped_source_alias}] <a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
        else:
            formatted_title = (
                f'[{escaped_source_alias}] <span class="no-link">{escaped_title}</span>'
            )

        if rank_display:
            formatted_title += f" {rank_display}"
        if title_data["time_display"]:
            escaped_time = ReportGenerator._html_escape(title_data["time_display"])
            formatted_title += f" <font color='grey'>- {escaped_time}</font>"
        if title_data["count"] > 1:
            formatted_title += f" <font color='green'>({title_data['count']}次)</font>"

        if title_data["is_new"]:
            formatted_title = f"<div class='new-title'>🆕 {formatted_title}</div>"

        return formatted_title

    @staticmethod
    def _render_html_content(
        report_data: Dict, total_titles: int, is_daily: bool = False
    ) -> str:
        """渲染HTML内容"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>频率词统计报告</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1, h2 { color: #333; }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .word { font-weight: bold; }
                .count { text-align: center; }
                .percentage { text-align: center; }
                .titles { max-width: 500px; }
                .source { color: #666; font-style: italic; }
                .error { color: #d9534f; }
                .news-link { 
                    color: #007bff; 
                    text-decoration: none; 
                    border-bottom: 1px dotted #007bff;
                }
                .news-link:hover { 
                    color: #0056b3; 
                    text-decoration: underline; 
                }
                .news-link:visited { 
                    color: #6f42c1; 
                }
                .no-link { 
                    color: #333; 
                }
                .new-title {
                    background-color: #fff3cd;
                    border: 1px solid #ffc107;
                    border-radius: 3px;
                    padding: 2px 6px;
                    margin: 2px 0;
                }
                .new-section {
                    background-color: #d1ecf1;
                    border: 1px solid #bee5eb;
                    border-radius: 5px;
                    padding: 10px;
                    margin-top: 10px;
                }
                .new-section h3 {
                    color: #0c5460;
                    margin-top: 0;
                }
            </style>
        </head>
        <body>
            <h1>频率词统计报告</h1>
        """

        if is_daily:
            html += "<p>报告类型: 当日汇总</p>"

        now = TimeHelper.get_beijing_time()
        html += f"<p>总标题数: {total_titles}</p>"
        html += f"<p>生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"

        # 渲染失败平台
        if report_data["failed_ids"]:
            html += """
            <div class="error">
                <h2>请求失败的平台</h2>
                <ul>
            """
            for id_value in report_data["failed_ids"]:
                html += f"<li>{ReportGenerator._html_escape(id_value)}</li>"
            html += """
                </ul>
            </div>
            """

        # 渲染统计表格
        html += """
            <table>
                <tr>
                    <th>排名</th>
                    <th>频率词</th>
                    <th>出现次数</th>
                    <th>占比</th>
                    <th>相关标题</th>
                </tr>
        """

        for i, stat in enumerate(report_data["stats"], 1):
            formatted_titles = []

            for title_data in stat["titles"]:
                formatted_title = ReportGenerator._format_title_html(title_data)
                formatted_titles.append(formatted_title)

            escaped_word = ReportGenerator._html_escape(stat["word"])
            html += f"""
                <tr>
                    <td>{i}</td>
                    <td class="word">{escaped_word}</td>
                    <td class="count">{stat['count']}</td>
                    <td class="percentage">{stat.get('percentage', 0)}%</td>
                    <td class="titles">{"<br>".join(formatted_titles)}</td>
                </tr>
            """

        html += """
            </table>
        """

        # 渲染新增新闻部分
        if report_data["new_titles"]:
            html += f"""
            <div class="new-section">
                <h3>🆕 本次新增热点新闻 (共 {report_data['total_new_count']} 条)</h3>
            """

            for source_data in report_data["new_titles"]:
                escaped_source = ReportGenerator._html_escape(
                    source_data["source_alias"]
                )
                html += (
                    f"<h4>{escaped_source} ({len(source_data['titles'])} 条)</h4><ul>"
                )

                for title_data in source_data["titles"]:
                    title_data_copy = title_data.copy()
                    title_data_copy["is_new"] = False
                    formatted_title = ReportGenerator._format_title_html(
                        title_data_copy
                    )
                    # 移除来源标签
                    if "] " in formatted_title:
                        formatted_title = formatted_title.split("] ", 1)[1]
                    html += f"<li>{formatted_title}</li>"

                html += "</ul>"

            html += "</div>"

        html += """
        </body>
        </html>
        """

        return html

    @staticmethod
    def _format_title_feishu(title_data: Dict, show_source: bool = True) -> str:
        """格式化飞书标题显示"""
        rank_display = StatisticsCalculator._format_rank_for_feishu(
            title_data["ranks"], title_data["rank_threshold"]
        )

        link_url = title_data["mobile_url"] or title_data["url"]
        if link_url:
            formatted_title = f"[{title_data['title']}]({link_url})"
        else:
            formatted_title = title_data["title"]

        title_prefix = "🆕 " if title_data["is_new"] else ""

        if show_source:
            result = f"<font color='grey'>[{title_data['source_alias']}]</font> {title_prefix}{formatted_title}"
        else:
            result = f"{title_prefix}{formatted_title}"

        if rank_display:
            result += f" {rank_display}"
        if title_data["time_display"]:
            result += f" <font color='grey'>- {title_data['time_display']}</font>"
        if title_data["count"] > 1:
            result += f" <font color='green'>({title_data['count']}次)</font>"

        return result

    @staticmethod
    def _render_feishu_content(report_data: Dict) -> str:
        """渲染飞书内容"""
        text_content = ""

        # 渲染热点词汇统计
        if report_data["stats"]:
            text_content += "📊 **热点词汇统计**\n\n"

        total_count = len(report_data["stats"])

        for i, stat in enumerate(report_data["stats"]):
            word = stat["word"]
            count = stat["count"]

            sequence_display = f"<font color='grey'>[{i + 1}/{total_count}]</font>"

            if count >= 10:
                text_content += f"🔥 {sequence_display} **{word}** : <font color='red'>{count}</font> 条\n\n"
            elif count >= 5:
                text_content += f"📈 {sequence_display} **{word}** : <font color='orange'>{count}</font> 条\n\n"
            else:
                text_content += f"📌 {sequence_display} **{word}** : {count} 条\n\n"

            for j, title_data in enumerate(stat["titles"], 1):
                formatted_title = ReportGenerator._format_title_feishu(
                    title_data, show_source=True
                )
                text_content += f"  {j}. {formatted_title}\n"

                if j < len(stat["titles"]):
                    text_content += "\n"

            if i < len(report_data["stats"]) - 1:
                text_content += f"\n{CONFIG['FEISHU_SEPARATOR']}\n\n"

        if not text_content:
            text_content = "📭 暂无匹配的热点词汇\n\n"

        # 渲染新增新闻部分
        if report_data["new_titles"]:
            if text_content and "暂无匹配" not in text_content:
                text_content += f"\n{CONFIG['FEISHU_SEPARATOR']}\n\n"

            text_content += (
                f"🆕 **本次新增热点新闻** (共 {report_data['total_new_count']} 条)\n\n"
            )

            for source_data in report_data["new_titles"]:
                text_content += f"**{source_data['source_alias']}** ({len(source_data['titles'])} 条):\n"

                for j, title_data in enumerate(source_data["titles"], 1):
                    title_data_copy = title_data.copy()
                    title_data_copy["is_new"] = False
                    formatted_title = ReportGenerator._format_title_feishu(
                        title_data_copy, show_source=False
                    )
                    text_content += f"  {j}. {formatted_title}\n"

                text_content += "\n"

        # 渲染失败平台
        if report_data["failed_ids"]:
            if text_content and "暂无匹配" not in text_content:
                text_content += f"\n{CONFIG['FEISHU_SEPARATOR']}\n\n"

            text_content += "⚠️ **数据获取失败的平台：**\n\n"
            for i, id_value in enumerate(report_data["failed_ids"], 1):
                text_content += f"  • <font color='red'>{id_value}</font>\n"

        # 添加时间戳
        now = TimeHelper.get_beijing_time()
        text_content += f"\n\n<font color='grey'>更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}</font>"

        return text_content

    @staticmethod
    def send_to_feishu(
        stats: List[Dict],
        failed_ids: Optional[List] = None,
        report_type: str = "单次爬取",
        new_titles: Optional[Dict] = None,
        id_to_alias: Optional[Dict] = None,
    ) -> bool:
        """发送数据到飞书"""
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])

        if not webhook_url:
            print(f"FEISHU_WEBHOOK_URL未设置，跳过飞书通知")
            return False

        headers = {"Content-Type": "application/json"}
        total_titles = sum(len(stat["titles"]) for stat in stats if stat["count"] > 0)

        # 数据处理层
        report_data = ReportGenerator._prepare_report_data(
            stats, failed_ids, new_titles, id_to_alias
        )

        # 渲染层
        text_content = ReportGenerator._render_feishu_content(report_data)

        now = TimeHelper.get_beijing_time()
        payload = {
            "msg_type": "text",
            "content": {
                "total_titles": total_titles,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "report_type": report_type,
                "text": text_content,
            },
        }

        try:
            response = requests.post(webhook_url, headers=headers, json=payload)
            if response.status_code == 200:
                print(f"飞书通知发送成功 [{report_type}]")
                return True
            else:
                print(
                    f"飞书通知发送失败 [{report_type}]，状态码：{response.status_code}"
                )
                return False
        except Exception as e:
            print(f"飞书通知发送出错 [{report_type}]：{e}")
            return False


# 新增Bark推送函数
def send_to_bark(title: str, body: str, subtitle: str = "") -> bool:
    """向Bark服务推送消息，支持标题、副标题和正文"""
    if not CONFIG.get("BARK_ENABLE", False):
        print("Bark推送开关关闭，跳过发送。")
        return False

    device_key = CONFIG.get("BARK_DEVICE_KEY", "")
    server_url = CONFIG.get("BARK_SERVER_URL", "https://api.day.app")

    if not device_key:
        print("Bark设备Key未配置，跳过发送。")
        return False

    url = f"{server_url}/push"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {
        "device_key": device_key,
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "sound": "minuet",
        "group": "TrendRadar",
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status()
        print("Bark推送成功")
        return True
    except Exception as e:
        print(f"Bark推送失败: {e}")
        return False


# 统一推送函数
def send_reports(report_text: str):
    """统一推送报告，执行飞书和Bark推送，均遵守开关"""
    # 飞书推送
    try:
        if CONFIG.get("FEISHU_ENABLE", False):
            webhook_url = os.getenv("FEISHU_WEBHOOK_URL", CONFIG.get("FEISHU_WEBHOOK_URL", ""))
            if webhook_url:
                headers = {"Content-Type": "application/json; charset=utf-8"}
                data = {"msg_type": "text", "content": {"text": report_text}}
                r = requests.post(webhook_url, headers=headers, data=json.dumps(data), timeout=10)
                r.raise_for_status()
                print("飞书推送成功")
            else:
                print("飞书Webhook未配置或无效，跳过飞书推送")
        else:
            print("飞书推送开关关闭，跳过飞书推送")
    except Exception as e:
        print(f"飞书推送异常: {e}")

    # Bark推送
    send_to_bark("TrendRadar 日报", report_text)


class NewsAnalyzer:
    """新闻分析器"""

    def __init__(
        self,
        request_interval: int = CONFIG["REQUEST_INTERVAL"],
        feishu_report_type: str = CONFIG["FEISHU_REPORT_TYPE"],
        rank_threshold: int = CONFIG["RANK_THRESHOLD"],
    ):
        self.request_interval = request_interval
        self.feishu_report_type = feishu_report_type
        self.rank_threshold = rank_threshold
        self.is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"

        self.proxy_url = None
        if not self.is_github_actions and CONFIG["USE_PROXY"]:
            self.proxy_url = CONFIG["DEFAULT_PROXY"]
            print("本地环境，使用代理")
        elif not self.is_github_actions and not CONFIG["USE_PROXY"]:
            print("本地环境，未启用代理")
        else:
            print("GitHub Actions环境，不使用代理")

        self.data_fetcher = DataFetcher(self.proxy_url)

    def generate_daily_summary(self) -> Optional[str]:
        """生成当日统计报告"""
        print("生成当日统计报告...")

        all_results, id_to_alias, title_info = DataProcessor.read_all_today_titles()

        if not all_results:
            print("没有找到当天的数据")
            return None

        total_titles = sum(len(titles) for titles in all_results.values())
        print(f"读取到 {total_titles} 个标题")

        latest_new_titles = DataProcessor.detect_latest_new_titles(id_to_alias)
        if latest_new_titles:
            total_new_count = sum(len(titles) for titles in latest_new_titles.values())
            print(f"检测到 {total_new_count} 条最新新增新闻")

        word_groups, filter_words = DataProcessor.load_frequency_words()

        stats, total_titles = StatisticsCalculator.count_word_frequency(
            all_results,
            word_groups,
            filter_words,
            id_to_alias,
            title_info,
            self.rank_threshold,
            latest_new_titles,
        )

        html_file = ReportGenerator.generate_html_report(
            stats,
            total_titles,
            is_daily=True,
            new_titles=latest_new_titles,
            id_to_alias=id_to_alias,
        )
        print(f"当日HTML统计报告已生成: {html_file}")

        if self.feishu_report_type in ["daily", "both"]:
            ReportGenerator.send_to_feishu(
                stats, [], "当日汇总", latest_new_titles, id_to_alias
            )

        return html_file

    def run(self) -> None:
        """执行分析流程"""
        now = TimeHelper.get_beijing_time()
        print(f"当前北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        feishu_on = CONFIG.get("FEISHU_ENABLE", False)
        bark_on = CONFIG.get("BARK_ENABLE", False)
        continue_crawl = CONFIG.get("CONTINUE_CRAWL_IF_PUSH_ALL_OFF", True)

        if not feishu_on and not bark_on:
            if continue_crawl:
                print("飞书和Bark推送均关闭，且配置允许继续爬虫，程序继续执行核心业务。")
            else:
                print("飞书和Bark推送均关闭，且配置不允许继续爬虫，程序退出。")
                return  # 直接返回终止后续执行

        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])
        if not webhook_url and not CONFIG["CONTINUE_WITHOUT_FEISHU"]:
            print(
                "错误: FEISHU_WEBHOOK_URL未设置且CONTINUE_WITHOUT_FEISHU为False，程序退出"
            )
            return

        if not webhook_url:
            print("FEISHU_WEBHOOK_URL未设置，将继续执行爬虫但不发送飞书通知")

        ids = [
            ("toutiao", "今日头条"),
            ("baidu", "百度热搜"),
            ("wallstreetcn-hot", "华尔街见闻"),
            ("thepaper", "澎湃新闻"),
            ("bilibili-hot-search", "bilibili 热搜"),
            ("cls-hot", "财联社热门"),
            ("ifeng", "凤凰网"),
            "tieba",
            "weibo",
            "douyin",
            "zhihu",
        ]

        print(f"开始爬取数据，请求间隔 {self.request_interval} 毫秒")
        FileHelper.ensure_directory_exists("output")

        results, id_to_alias, failed_ids = self.data_fetcher.crawl_websites(
            ids, self.request_interval
        )

        title_file = DataProcessor.save_titles_to_file(results, id_to_alias, failed_ids)
        print(f"标题已保存到: {title_file}")

        new_titles = DataProcessor.detect_latest_new_titles(id_to_alias)

        # 构建标题信息
        time_info = Path(title_file).stem
        title_info = {}
        for source_id, titles_data in results.items():
            title_info[source_id] = {}
            for title, title_data in titles_data.items():
                ranks = title_data.get("ranks", [])
                url = title_data.get("url", "")
                mobile_url = title_data.get("mobileUrl", "")

                title_info[source_id][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }

        word_groups, filter_words = DataProcessor.load_frequency_words()

        stats, total_titles = StatisticsCalculator.count_word_frequency(
            results,
            word_groups,
            filter_words,
            id_to_alias,
            title_info,
            self.rank_threshold,
            new_titles,
        )

        if self.feishu_report_type in ["current", "both"]:
            ReportGenerator.send_to_feishu(
                stats, failed_ids, "单次爬取", new_titles, id_to_alias
            )

        html_file = ReportGenerator.generate_html_report(
            stats, total_titles, failed_ids, False, new_titles, id_to_alias
        )
        print(f"HTML报告已生成: {html_file}")

        # 统一调用推送，发送简要文本报告
        report_text = f"今日爬取完成，统计报告生成，标题总数: {total_titles}"
        send_reports(report_text)

        daily_html = self.generate_daily_summary()

        if not self.is_github_actions and html_file:
            file_url = "file://" + str(Path(html_file).resolve())
            print(f"正在打开HTML报告: {file_url}")
            webbrowser.open(file_url)

            if daily_html:
                daily_url = "file://" + str(Path(daily_html).resolve())
                print(f"正在打开当日统计报告: {daily_url}")
                webbrowser.open(daily_url)


def main():
    analyzer = NewsAnalyzer(
        request_interval=CONFIG["REQUEST_INTERVAL"],
        feishu_report_type=CONFIG["FEISHU_REPORT_TYPE"],
        rank_threshold=CONFIG["RANK_THRESHOLD"],
    )
    analyzer.run()


if __name__ == "__main__":
    main()

# ================== CONFIG ==================

CONFIG = {
    "FEISHU_SEPARATOR": "━━━━━━━━━━━━━━━━━━━",  # 飞书消息分割线
    "REQUEST_INTERVAL": 1000,  # 请求间隔(毫秒)
    "FEISHU_REPORT_TYPE": "daily",  # 飞书报告类型: "current"|"daily"|"both"
    "RANK_THRESHOLD": 5,  # 排名高亮阈值
    "USE_PROXY": True,  # 是否启用代理
    "DEFAULT_PROXY": "http://127.0.0.1:10086",
    "CONTINUE_WITHOUT_FEISHU": True,  # 无Webhook继续爬取
    "FEISHU_WEBHOOK_URL": "",  # 飞书机器人Webhook地址(通过环境变量或Secrets设置)
    "BARK_KEY":"",  # Bark推送Key(从环境变量读取)
    "USE_BARK_PUSH": False,  # 布尔开关，True启用Bark推送，False使用飞书推送
}

# ================== Bark 推送相关 ==================

def send_to_bark_json(
    device_key: str,
    title: str,
    body: str,
    sound: str = "default",
    group: str = "",
    badge: int = 0,
    extras: dict = None,
) -> bool:
    """
    通过POST请求向Bark推送API发送JSON消息。
    :param device_key: Bark设备Key，必填
    :param title: 消息标题
    :param body: 消息正文
    :param sound: 推送声音，默认"default"
    :param group: 推送组名，可选
    :param badge: 桌面角标数字，默认0
    :param extras: 额外字段字典，支持自定义，如url/copy等
    :return: 推送成功返回True，失败False
    """
    url = "https://api.day.app/v1/sender"  # Bark API的JSON推送地址
    headers = {"Content-Type": "application/json"}  # 请求头

    data = {
        "device_key": device_key,
        "title": title,
        "body": body,
        "sound": sound,
        "group": group,
        "badge": badge,
    }
    if extras:
        data.update(extras)  # 合并额外自定义字段

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)  # 发送POST请求
        response.raise_for_status()  # 如果状态码非200，将抛异常
        print("Bark推送成功")
        return True
    except Exception as e:
        print(f"Bark推送失败，异常: {e}")
        return False

# ================== 飞书推送相关 ==================

def send_to_feishu_json(data: dict) -> bool:
    """
    发送JSON数据到飞书机器人Webhook。
    :param data: 飞书消息体JSON
    :return: 成功True，失败False
    """
    webhook = CONFIG["FEISHU_WEBHOOK_URL"]
    if not webhook:
        print("飞书Webhook未配置，无法推送")
        return False

    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(webhook, json=data, headers=headers, timeout=10)
        resp.raise_for_status()
        print("飞书推送成功")
        return True
    except Exception as e:
        print(f"飞书推送失败: {e}")
        return False

# ================== 消息构造示例 ==================

def build_feishu_message_example(new_titles_count: int) -> dict:
    """
    构造示例飞书卡片消息体，动态显示匹配到的新闻条数。
    :param new_titles_count: 新增新闻条数，用于文本展示
    """
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},  # 宽屏模式
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"<at id=all></at> 今日新闻更新，共匹配到{new_titles_count}条热点",
                        "tag": "lark_md",  # 使用飞书Markdown格式
                    },
                }
            ],
        },
    }

def build_bark_message_example(new_titles_count: int) -> Tuple[str, str]:
    """
    构建Bark推送的消息标题和正文。
    :param new_titles_count: 新增新闻数量，用于正文说明
    :return: (标题, 正文) 元组
    """
    title = "新闻热点更新"
    body = f"匹配到 {new_titles_count} 条热点新闻\n请查看详细报告。"
    return title, body

# ================== 发送通知 ==================

def push_notification(new_titles_count: int) -> None:
    """
    根据配置选择推送方式(飞书或Bark)并发送推送通知。
    :param new_titles_count: 新增新闻条数，构造消息使用
    """
    if CONFIG["USE_BARK_PUSH"]:
        # 使用Bark推送
        bark_key = CONFIG["BARK_KEY"]
        if not bark_key:
            print("Bark Key未配置，无法推送")
            return

        title, body = build_bark_message_example(new_titles_count)

        extras = {
            "url": "https://your-report-url.com",  # 点击通知后打开的链接
            "copy": "自动复制文本示例",  # 可自动复制的文本
            "automaticallyCopy": True,  # 是否自动复制
        }

        send_to_bark_json(
            device_key=bark_key,
            title=title,
            body=body,
            sound="notification",  # 推送声音
            group="热点新闻",
            badge=new_titles_count,
            extras=extras,
        )
    else:
        # 使用飞书推送
        if not CONFIG["FEISHU_WEBHOOK_URL"]:
            print("飞书Webhook未配置，无法推送")
            return

        feishu_msg = build_feishu_message_example(new_titles_count)
        send_to_feishu_json(feishu_msg)

# ================== 示例主入口调用 ==================

def main():
    # 初始化您的分析器对象（含爬虫、分析部分略，保留您原始代码）
    analyzer = NewsAnalyzer(
        request_interval=CONFIG["REQUEST_INTERVAL"],
        feishu_report_type=CONFIG["FEISHU_REPORT_TYPE"],
        rank_threshold=CONFIG["RANK_THRESHOLD"],
    )

    analyzer.run()  # 执行爬取与分析流程

    # 这里演示用一个示例新增条数通知推送，您需替换为实际计算结果
    new_hot_titles_count = 3  # 这里演示传入3条新增新闻

    # 推送通知（飞书或Bark，根据配置开关决定）
    push_notification(new_hot_titles_count)


if __name__ == "__main__":
    main()

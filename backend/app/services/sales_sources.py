SALES_ORDER_TABLE_SQL = "`dwd`.`销售单查询_进口超市上海仓补全`"
SALES_ORDER_TABLE_REFERENCE = "dwd.`销售单查询_进口超市上海仓补全`"
ACTIVE_SALES_ORDER_SQL = "COALESCE(`订单状态`, '') NOT LIKE '%取消%'"
POSITIVE_SALES_ORDER_COUNT_SQL = "COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END)"

BRAND_EXPRESSION_SQL = """
    CASE
      WHEN NULLIF(`品牌`, '') IS NOT NULL THEN `品牌`
      WHEN `货品名称` LIKE '资生堂%' THEN '资生堂'
      WHEN `货品名称` LIKE '兰蔻%' THEN '兰蔻'
      WHEN `货品名称` LIKE 'YSL%' THEN 'YSL'
      WHEN `货品名称` LIKE '圣罗兰%' THEN '圣罗兰'
      WHEN `货品名称` LIKE '植村秀%' THEN '植村秀'
      WHEN `货品名称` LIKE 'HR赫莲娜%' THEN 'HR赫莲娜'
      WHEN `货品名称` LIKE '赫莲娜%' THEN '赫莲娜'
      WHEN `货品名称` LIKE '科颜氏%' THEN '科颜氏'
      WHEN `货品名称` LIKE '修丽可%' THEN '修丽可'
      WHEN `货品名称` LIKE '阿玛尼%' THEN '阿玛尼'
      WHEN `货品名称` LIKE '欧莱雅%' THEN '欧莱雅'
      WHEN `货品名称` LIKE '理肤泉%' THEN '理肤泉'
      WHEN `货品名称` LIKE '薇姿%' THEN '薇姿'
      WHEN `货品名称` LIKE '适乐肤%' THEN '适乐肤'
      ELSE '未识别品牌'
    END
"""

PRODUCT_TYPE_EXPRESSION_SQL = "COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类')"


def is_online_sales_channel(
    category: object,
    platform: object,
    channel_name: object,
) -> bool:
    """Classify sales channels using the confirmed business rules."""
    category_text = str(category or "").strip() or "未分类"
    platform_text = str(platform or "").strip() or "未设置"
    channel_text = str(channel_name or "").strip() or "未归类"
    if category_text == "销售部渠道":
        return False
    if category_text == "运营部线上渠道":
        return channel_text != "桢植线下快闪店"
    if category_text == "梧颜":
        return platform_text != "未设置"
    if channel_text.startswith("渠道预留"):
        return False
    if channel_text.startswith("海旅"):
        return True
    return platform_text != "未设置" or any(
        keyword in channel_text for keyword in ("快手", "微店", "微信小店", "抖店")
    )

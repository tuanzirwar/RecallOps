"""Generate a deterministic, realistic-style RecallOps retrieval benchmark.

The data is synthetic and intentionally labelled as such. It exercises variations
that commonly appear in incident chat: error-code lookups, abbreviated service
names, paraphrased symptoms, root-cause queries, and unrelated questions.
"""
from __future__ import annotations

import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "datasets"
RNG = random.Random(20260901)

DOMAINS = [
    ("payment", "支付", "PAY"), ("auth", "认证", "AUTH"), ("inventory", "库存", "STOCK"),
    ("search", "检索", "SEARCH"), ("notification", "通知", "NOTIFY"), ("order", "订单", "ORDER"),
    ("analytics", "分析", "ANALYTICS"), ("media", "媒体", "MEDIA"), ("coupon", "优惠券", "COUPON"),
    ("shipping", "物流", "SHIP"), ("billing", "计费", "BILL"), ("catalog", "商品目录", "CATALOG"),
    ("risk", "风控", "RISK"), ("member", "会员", "MEMBER"), ("settlement", "结算", "SETTLE"),
]

FAILURES = [
    ("请求超时", "接口 P95 延迟超过 3 秒，用户请求持续超时", "PostgreSQL 连接池耗尽", "扩容连接池并限制重试风暴", "database-service"),
    ("状态不同步", "上游处理成功但页面状态迟迟没有更新", "异步消费者积压且重试策略错误", "恢复消费者并补偿积压事件", "mq-service"),
    ("重复处理", "同一业务单据被处理两次，出现重复扣款或重复通知", "消息重复投递且缺少幂等键", "以业务事件 ID 增加幂等记录", "mq-service"),
    ("查询为空", "数据已存在但接口返回空结果", "索引任务积压导致搜索索引滞后", "重启索引 worker 并重放失败任务", "search-service"),
    ("权限拒绝", "已授权用户调用接口却被拒绝", "缓存的 RBAC 角色版本没有刷新", "失效权限缓存并发布角色版本", "identity-service"),
    ("流量突增", "活动开始后接口错误率和延迟同时升高", "热点缓存同时过期造成回源洪峰", "缓存增加随机过期并预热热点", "cache-service"),
    ("回调失败", "第三方回调持续验签失败", "回调证书过期", "轮换证书并补偿失败回调", "gateway-service"),
    ("数据延迟", "运营侧数据停留在数小时前", "消费者分区再均衡循环", "修复消费者超时配置并重启消费组", "mq-service"),
    ("上传失败", "大文件传输到一半被网关中断", "请求体大小限制低于业务配置", "提高网关请求体限制并增加分片上传", "gateway-service"),
    ("配额超限", "请求被限流且业务量未达到预估峰值", "租户限流配置被错误继承", "修正租户限流配置并增加告警", "rate-limit-service"),
]

PARAPHRASES = {
    "请求超时": "调用频繁卡住并出现超时", "状态不同步": "上游完成后页面结果却没有刷新",
    "重复处理": "业务单据疑似被反复执行", "查询为空": "明明有数据却查不到",
    "权限拒绝": "已经授权的账号仍然被拦截", "流量突增": "活动流量上来后接口开始雪崩",
    "回调失败": "第三方通知持续验签不通过", "数据延迟": "看板数据滞后了很久",
    "上传失败": "大文件总是在传输中断开", "配额超限": "还没到预估峰值就被限流",
}

SEED_INCIDENTS = [
    {"id": "INC-001", "title": "支付回调延迟", "symptom": "付款成功后订单状态长时间未更新", "root_cause": "order-service 数据库连接池耗尽", "resolution": "max_pool_size 从 50 调整到 200", "error_codes": ["PAYMENT_5032"], "services": ["payment-service", "order-service"]},
    {"id": "INC-002", "title": "登录接口大量超时", "symptom": "用户无法登录且网关返回超时", "root_cause": "auth-service Redis 连接数达到上限", "resolution": "扩容 Redis 并限制重试", "error_codes": ["AUTH_5041"], "services": ["auth-service", "gateway-service"]},
    {"id": "INC-003", "title": "库存重复扣减", "symptom": "同一订单的库存被扣减两次", "root_cause": "消息消费超时后重复投递且缺少幂等键", "resolution": "以 order_id 建立消费幂等记录", "error_codes": ["STOCK_4092"], "services": ["inventory-service", "mq-service"]},
    {"id": "INC-004", "title": "图片上传失败", "symptom": "大图片上传到一半失败", "root_cause": "网关请求体限制小于业务上限", "resolution": "将 client_max_body_size 调整为 50m", "error_codes": ["UPLOAD_4130"], "services": ["media-service", "gateway-service"]},
    {"id": "INC-005", "title": "搜索结果为空", "symptom": "商品存在但搜索不到", "root_cause": "search-service 索引任务积压", "resolution": "恢复索引 worker 并重放失败任务", "error_codes": ["SEARCH_2004"], "services": ["search-service", "catalog-service"]},
    {"id": "INC-006", "title": "优惠券超发", "symptom": "活动优惠券领取数量超过预算", "root_cause": "coupon-service 分布式锁租约提前过期", "resolution": "启用锁续期并增加数据库唯一约束", "error_codes": ["COUPON_5006"], "services": ["coupon-service", "campaign-service"]},
    {"id": "INC-007", "title": "订单创建雪崩", "symptom": "促销开始后下单接口延迟急剧升高", "root_cause": "pricing-service 缓存同时过期造成回源洪峰", "resolution": "缓存过期时间增加随机抖动并预热热点", "error_codes": ["ORDER_5038"], "services": ["order-service", "pricing-service"]},
    {"id": "INC-008", "title": "短信重复发送", "symptom": "用户收到多条相同验证码短信", "root_cause": "notification-service 重试没有发送幂等键", "resolution": "使用业务事件 ID 作为供应商幂等键", "error_codes": ["SMS_4293"], "services": ["notification-service", "auth-service"]},
    {"id": "INC-009", "title": "报表数据延迟", "symptom": "运营报表停留在两小时前", "root_cause": "analytics-service 消费者发生分区再均衡循环", "resolution": "修复消费者超时配置并重启消费组", "error_codes": ["REPORT_2060"], "services": ["analytics-service", "mq-service"]},
    {"id": "INC-010", "title": "退款状态不一致", "symptom": "退款成功但订单仍显示退款处理中", "root_cause": "refund-service 回调签名证书过期", "resolution": "轮换证书并补偿失败回调", "error_codes": ["REFUND_4017"], "services": ["refund-service", "order-service"]},
]


def synthetic_incidents(count: int = 150) -> list[dict]:
    rows = list(SEED_INCIDENTS)
    for number in range(1, count + 1):
        service, domain, prefix = DOMAINS[(number - 1) % len(DOMAINS)]
        failure, symptom, cause, resolution, dependency = FAILURES[(number * 7) % len(FAILURES)]
        region = ("华东", "华北", "华南", "海外")[number % 4]
        incident_id = f"INC-{number + 10:04d}"
        code = f"{prefix}_{5100 + number}"
        rows.append({
            "id": incident_id,
            "title": f"{domain}{failure}（{region}第{number}批）",
            "symptom": f"{region}生产环境第{number}批告警：{domain}{symptom}，影响 {service}-service 的核心链路",
            "root_cause": f"{service}-service {cause}",
            "resolution": resolution,
            "error_codes": [code],
            "services": [f"{service}-service", dependency],
            "metadata": {"region": region, "environment": "production", "failure": failure, "synthetic": True},
        })
    return rows


def answer_queries(incident: dict, qrels: dict[str, dict[str, list[str]]]) -> list[dict]:
    primary = incident["services"][0]
    code = incident["error_codes"][0]
    phrase = PARAPHRASES.get(incident.get("metadata", {}).get("failure", ""), incident["title"].split("（")[0])
    return [
        {"query": f"{code} 以前怎么处理？", "relevant": [incident["id"]], "query_type": "error_code"},
        {"query": incident["symptom"], "relevant": qrels["symptom"][incident["symptom"]], "query_type": "symptom_verbatim"},
        {"query": f"{primary} 在 {incident.get('metadata', {}).get('region', '线上')} {phrase}，有没有历史案例", "relevant": qrels["service_symptom"][(primary, incident["title"].split("（")[0], incident.get("metadata", {}).get("region", ""))], "query_type": "service_symptom"},
        {"query": f"{primary} 在 {incident.get('metadata', {}).get('region', '线上')} 的 {incident['root_cause'].split(primary)[-1].strip()} 如何排查", "relevant": qrels["root_cause"][incident["root_cause"]], "query_type": "root_cause"},
        {"query": f"{incident.get('metadata', {}).get('region', '线上')} 环境中，{incident['resolution']} 是解决过什么故障", "relevant": qrels["resolution_region"][(incident["resolution"], incident.get("metadata", {}).get("region", ""))], "query_type": "resolution"},
        {"query": incident["title"], "relevant": qrels["short_query"][incident["title"]], "query_type": "short_query"},
    ]


def no_answer_queries(count: int = 180) -> list[dict]:
    nouns = ["火星探测器", "卫星姿态控制", "核磁共振设备", "铁路信号灯", "海洋浮标", "无人机飞控", "气象雷达", "风力发电机", "工业机械臂", "显微镜成像", "港口吊机", "深海潜航器", "太阳能逆变器", "民航导航系统", "地震监测仪", "农业灌溉阀门", "高速列车受电弓", "激光测距仪", "智能电表", "海底光缆"]
    faults = ["燃料泄漏", "天线转速异常", "低温校准失败", "制动压力不足", "镜头抖动", "陀螺仪漂移", "液压回路告警", "电池热失控", "传感器零点漂移"]
    return [{"query": f"{nouns[i % len(nouns)]}{faults[(i * 3) % len(faults)]}历史故障", "relevant": [], "query_type": "no_answer"} for i in range(count)]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    incidents = synthetic_incidents()
    qrels: dict[str, dict] = {"symptom": {}, "service_symptom": {}, "root_cause": {}, "resolution_region": {}, "short_query": {}}
    for incident in incidents:
        qrels["symptom"].setdefault(incident["symptom"], []).append(incident["id"])
        region = incident.get("metadata", {}).get("region", "")
        qrels["service_symptom"].setdefault((incident["services"][0], incident["title"].split("（")[0], region), []).append(incident["id"])
        qrels["root_cause"].setdefault(incident["root_cause"], []).append(incident["id"])
        qrels["resolution_region"].setdefault((incident["resolution"], region), []).append(incident["id"])
        short = incident["title"]
        qrels["short_query"].setdefault(short, []).append(incident["id"])
    queries = [query for incident in incidents for query in answer_queries(incident, qrels)] + no_answer_queries()
    RNG.shuffle(queries)
    DATA.mkdir(parents=True, exist_ok=True)
    write_jsonl(DATA / "incidents.jsonl", incidents)
    write_jsonl(DATA / "queries.jsonl", queries)
    print(json.dumps({"incidents": len(incidents), "queries": len(queries), "answer_queries": len(queries) - 180, "no_answer_queries": 180, "seed": 20260901}, ensure_ascii=False))

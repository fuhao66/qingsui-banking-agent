import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionFactory
from app.db.models import (
    Account,
    BankCard,
    InvestmentProduct,
    LifeEvent,
    Payee,
    SecurityState,
    Subscription,
    Transaction,
    User,
)
from app.domain.constants import (
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_PRIMARY_PAYEE_ID,
    DEMO_SAVINGS_ACCOUNT_ID,
    DEMO_USER_ID,
)


def stable_id(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"banking-agent-demo:{key}"))


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + month - 1 + offset
    return absolute // 12, absolute % 12 + 1


def transaction(
    key: str,
    account_id: str,
    direction: str,
    category: str,
    amount: str,
    description: str,
    occurred_at: datetime,
    *,
    merchant: str | None = None,
    counterparty_name: str | None = None,
    recurring: bool = False,
    risk_flag: str | None = None,
) -> Transaction:
    return Transaction(
        id=stable_id(f"transaction:{key}"),
        account_id=account_id,
        direction=direction,
        category=category,
        amount=Decimal(amount),
        currency="CNY",
        merchant=merchant,
        counterparty_name=counterparty_name,
        description=description,
        status="completed",
        occurred_at=occurred_at,
        is_recurring=recurring,
        risk_flag=risk_flag,
        external_reference=f"SEED-{key.upper()}",
    )


def build_transactions() -> list[Transaction]:
    rows: list[Transaction] = []
    for month_offset in range(12):
        year, month = shift_month(2026, 8, -month_offset)
        prefix = f"{year}{month:02d}"
        variation = Decimal(month_offset % 4) * Decimal("6.50")

        rows.extend(
            [
                transaction(
                    f"{prefix}-salary",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "credit",
                    "income",
                    "15000.00",
                    "工资入账",
                    datetime(year, month, 5, 9, 0, tzinfo=UTC),
                    counterparty_name="云帆科技有限公司",
                ),
                transaction(
                    f"{prefix}-rent",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "housing",
                    "3200.00",
                    "房租",
                    datetime(year, month, 1, 8, 30, tzinfo=UTC),
                    counterparty_name="张女士",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-utilities",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "utilities",
                    str(Decimal("186.30") + variation),
                    "水电燃气费",
                    datetime(year, month, 9, 10, 10, tzinfo=UTC),
                    merchant="城市生活缴费",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-mobile",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "utilities",
                    "99.00",
                    "手机话费",
                    datetime(year, month, 12, 7, 40, tzinfo=UTC),
                    merchant="中国移动",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-video",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "subscription",
                    "25.00",
                    "视频会员自动续费",
                    datetime(year, month, 16, 6, 0, tzinfo=UTC),
                    merchant="星幕视频",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-music",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "subscription",
                    "15.00",
                    "音乐会员自动续费",
                    datetime(year, month, 18, 6, 0, tzinfo=UTC),
                    merchant="听风音乐",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-cloud",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "subscription",
                    "18.00",
                    "云盘会员自动续费",
                    datetime(year, month, 20, 6, 0, tzinfo=UTC),
                    merchant="云盒存储",
                    recurring=True,
                ),
                transaction(
                    f"{prefix}-saving",
                    DEMO_SAVINGS_ACCOUNT_ID,
                    "credit",
                    "internal_transfer",
                    "2000.00",
                    "每月储蓄计划转入",
                    datetime(year, month, 6, 10, 0, tzinfo=UTC),
                    counterparty_name="工资卡",
                    recurring=True,
                ),
            ]
        )

        for index, amount in enumerate(("32.80", "46.50", "68.00", "24.60", "88.00"), 1):
            adjusted = Decimal(amount) + variation
            rows.append(
                transaction(
                    f"{prefix}-dining-{index}",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "dining",
                    str(adjusted),
                    "餐饮消费",
                    datetime(
                        year, month, min(3 + index * 4, 27), 12 + index % 2, 20, tzinfo=UTC
                    ),
                    merchant=("禾味餐厅", "街角咖啡", "轻食研究所", "川味小馆", "麦香烘焙")[
                        index - 1
                    ],
                )
            )

        for index, amount in enumerate(("18.00", "26.40", "12.00", "34.50"), 1):
            rows.append(
                transaction(
                    f"{prefix}-transport-{index}",
                    DEMO_CHECKING_ACCOUNT_ID,
                    "debit",
                    "transport",
                    amount,
                    "出行消费",
                    datetime(year, month, 4 + index * 5, 8, 15, tzinfo=UTC),
                    merchant="城市出行",
                )
            )

        shopping_amount = "768.00" if month_offset == 0 else str(Decimal("286.00") + variation)
        rows.append(
            transaction(
                f"{prefix}-shopping",
                DEMO_CHECKING_ACCOUNT_ID,
                "debit",
                "shopping",
                shopping_amount,
                "生活购物",
                datetime(year, month, 23, 20, 18, tzinfo=UTC),
                merchant="万象商城",
            )
        )

    rows.append(
        transaction(
            "202608-overseas-risk",
            DEMO_CHECKING_ACCOUNT_ID,
            "debit",
            "shopping",
            "899.00",
            "境外线上交易",
            datetime(2026, 8, 27, 2, 13, tzinfo=UTC),
            merchant="GLOBAL DIGITAL STORE",
            risk_flag="UNUSUAL_TIME_AND_REGION",
        )
    )
    return rows


async def seed_extended_catalog(session: AsyncSession) -> bool:
    inserted = False
    card_specs = [
        (
            "salary-debit",
            DEMO_CHECKING_ACCOUNT_ID,
            "青穗银联借记卡",
            "UnionPay",
            "6688",
            "50000.00",
        ),
        (
            "savings-debit",
            DEMO_SAVINGS_ACCOUNT_ID,
            "青穗储蓄卡",
            "UnionPay",
            "1024",
            "20000.00",
        ),
    ]
    for key, account_id, name, network, last4, daily_limit in card_specs:
        card_id = stable_id(f"card:{key}")
        if await session.get(BankCard, card_id) is None:
            session.add(
                BankCard(
                    id=card_id,
                    user_id=DEMO_USER_ID,
                    account_id=account_id,
                    card_name=name,
                    network=network,
                    masked_number=f"**** **** **** {last4}",
                    last4=last4,
                    status="active",
                    daily_limit=Decimal(daily_limit),
                )
            )
            inserted = True

    product_specs = [
        ("cash-plus", "青穗现金+", "cash_management", "low", "1.00", "1.60", "2.10", 0, "T+1", "低波动现金管理，适合短期闲置资金。"),
        ("steady-90", "稳盈90天", "fixed_income", "low", "1000.00", "2.40", "3.20", 3, "到期赎回", "以固收类资产为主，适合三个月以上持有。"),
        ("balanced-180", "均衡优选180天", "mixed", "medium", "5000.00", "3.20", "5.80", 6, "到期赎回", "股债均衡配置，净值会随市场波动。"),
        ("growth-360", "成长精选一年持有", "equity", "high", "10000.00", "-8.00", "12.00", 12, "最短持有一年", "权益资产占比较高，适合能承受较大波动的用户。"),
        ("green-bond", "绿色金融债精选", "bond", "medium", "1000.00", "2.80", "4.60", 6, "每月开放", "投资绿色金融主题债券，兼顾收益与流动性。"),
    ]
    for key, name, category, risk, minimum, low, high, term, liquidity, description in product_specs:
        product_id = stable_id(f"investment:{key}")
        if await session.get(InvestmentProduct, product_id) is None:
            session.add(
                InvestmentProduct(
                    id=product_id,
                    name=name,
                    category=category,
                    risk_level=risk,
                    min_amount=Decimal(minimum),
                    expected_return_low=Decimal(low),
                    expected_return_high=Decimal(high),
                    term_months=term,
                    liquidity=liquidity,
                    description=description,
                    status="active",
                )
            )
            inserted = True
    event_id = stable_id("life-event:partner-birthday")
    if await session.get(LifeEvent, event_id) is None:
        session.add(
            LifeEvent(
                id=event_id,
                user_id=DEMO_USER_ID,
                person="爱人",
                event_type="生日",
                event_date=datetime(2026, 11, 20, 0, 0, tzinfo=UTC),
                default_budget=Decimal("1000.00"),
                enabled=True,
            )
        )
        inserted = True
    await session.flush()
    return inserted


async def seed_demo_data(session: AsyncSession) -> bool:
    if await session.get(User, DEMO_USER_ID) is not None:
        inserted = await seed_extended_catalog(session)
        await session.commit()
        return inserted

    session.add(
        User(
            id=DEMO_USER_ID,
            display_name="刘女士",
            phone_masked="138****6688",
            customer_no="DEMO-2026-0001",
            risk_profile="balanced",
        )
    )
    await session.flush()

    session.add(SecurityState(user_id=DEMO_USER_ID, consecutive_failures=0))

    session.add_all(
        [
            Account(
                id=DEMO_CHECKING_ACCOUNT_ID,
                user_id=DEMO_USER_ID,
                name="工资卡",
                account_type="checking",
                masked_number="**** **** **** 6688",
                currency="CNY",
                balance=Decimal("28640.52"),
                status="active",
            ),
            Account(
                id=DEMO_SAVINGS_ACCOUNT_ID,
                user_id=DEMO_USER_ID,
                name="安心储蓄账户",
                account_type="savings",
                masked_number="**** **** **** 1024",
                currency="CNY",
                balance=Decimal("52000.00"),
                status="active",
            ),
        ]
    )
    await session.flush()

    payee_specs = [
        (DEMO_PRIMARY_PAYEE_ID, "王小明", "小王、上次聚餐", "招商银行", "2381", True, 3),
        (stable_id("payee:wang-xiao"), "王晓", "小王、产品部同事", "中国银行", "5176", True, 16),
        (stable_id("payee:mother"), "刘秀兰", "妈妈", "中国工商银行", "9032", True, 8),
        (stable_id("payee:landlord"), "张敏", "房东", "建设银行", "4418", True, 34),
        (stable_id("payee:lina"), "李娜", "大学同学", "交通银行", "7720", False, 82),
        (stable_id("payee:chenyu"), "陈宇", "摄影师", "浦发银行", "1098", False, 120),
    ]
    session.add_all(
        [
            Payee(
                id=payee_id,
                owner_user_id=DEMO_USER_ID,
                name=name,
                alias=alias,
                bank_name=bank,
                account_masked=f"**** **** **** {last4}",
                account_token=f"sandbox-payee-{last4}",
                phone_masked=f"138****{last4}",
                phone_last4=last4,
                is_frequent=frequent,
                last_transfer_at=datetime(2026, 8, 31, tzinfo=UTC) - timedelta(days=days_ago),
            )
            for payee_id, name, alias, bank, last4, frequent, days_ago in payee_specs
        ]
    )

    subscription_specs = [
        ("video", "星幕视频", "畅享会员", "25.00", 16, "app://star-video/cancel", "0.9970"),
        ("music", "听风音乐", "黑胶会员", "15.00", 18, "app://wind-music/cancel", "0.9920"),
        ("cloud", "云盒存储", "200GB 空间", "18.00", 20, "https://cloudbox.example/cancel", "0.9850"),
        ("fitness", "跃动健身", "月度训练计划", "99.00", 22, "客服电话 400-800-2026", "0.9410"),
        ("reading", "拾光阅读", "电子书会员", "12.00", 28, "app://reading/cancel", "0.9780"),
    ]
    session.add_all(
        [
            Subscription(
                id=stable_id(f"subscription:{key}"),
                user_id=DEMO_USER_ID,
                account_id=DEMO_CHECKING_ACCOUNT_ID,
                merchant=merchant,
                product_name=product_name,
                amount=Decimal(amount),
                currency="CNY",
                billing_cycle="monthly",
                status="active",
                next_charge_at=datetime(2026, 9, day, 6, 0, tzinfo=UTC),
                last_charge_at=datetime(2026, 8, day, 6, 0, tzinfo=UTC),
                cancellation_channel=channel,
                confidence=Decimal(confidence),
            )
            for key, merchant, product_name, amount, day, channel, confidence in subscription_specs
        ]
    )
    session.add_all(build_transactions())
    await seed_extended_catalog(session)
    await session.commit()
    return True


async def main() -> None:
    async with SessionFactory() as session:
        inserted = await seed_demo_data(session)
    print("Demo banking data seeded." if inserted else "Demo banking data already exists.")


if __name__ == "__main__":
    asyncio.run(main())

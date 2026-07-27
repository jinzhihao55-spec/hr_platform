"""数值口径公共函数。"""
from decimal import Decimal, ROUND_HALF_UP


def round_two(value: float) -> float:
    """四舍五入（HALF_UP）保留 2 位。

    报表口径统一使用 HALF_UP；内置 round() 是银行家舍入，
    且 float 直接 round 在 .005 边界上不稳定。"""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

import QuantLib as ql
from QuantLib.QuantLib import DateGeneration, Schedule
from 모듈1 import GET_DATE, GET_QUOTE, TREASURY_CURVE

ref_date = GET_DATE()
quote = GET_QUOTE(ref_date)
curve = TREASURY_CURVE(ref_date, quote)

#convert into Engine
spotCurveHandle = ql.YieldTermStructureHandle(curve)
bondEngine = ql.DiscountingBondEngine(spotCurveHandle)

#Treasury Bond Specification
issueDate = ql.Date(28, 12, 2021)
maturityDate = ql.Date(28, 12, 2023)
tenor = ql.Period(ql.Semiannual)
calendar = ql.UnitedStates()
convention = ql.ModifiedFollowing
dateGeneration = ql.DateGeneration.Backward
monthend = False
schedule = ql.Schedule(issueDate, maturityDate, tenor, calendar, convention, convention, dateGeneration, monthend)

dayCount = ql.ActualActual()
couponRate = [0.769]
settlementDay = 1
faceValue = 100

fixedRateBond = ql.FixedRateBond(settlementDay, faceValue, schedule, couponRate, dayCount)

fixedRateBond.setPricingEngine(bondEngine)

print("Bond Price = {}".format(round(fixedRateBond.NPV(),1)))
for c in fixedRateBond.cashflows():
    print('%20s %12f' % (c.date(), c.amount()))





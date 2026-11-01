"""Reference builder for the original personal tracker (v0).

Port this layout into backend/excel/builder.py. Run: python build_tracker.py out.xlsx
"""
from datetime import date as d
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule
from openpyxl.worksheet.table import Table, TableStyleInfo

IB, BIB, HF, TF, PE, AM, FT, DATA, EN, PS, TECH, OTH = ("Investment bank", "Boutique investment bank", "Hedge fund",
    "Trading firm", "Private equity / credit", "Asset manager", "Fintech", "Financial data", "Energy & commodities",
    "Professional services", "Tech", "Unconfirmed")
G, I, U = "Graduate", "Internship", "Not stated"

# company, firm type, role, programme, via, applied, stage reached, status, last update, next step, notes
# Example rows only. The real app builds these from the database.
R = [
("Example Bank", IB, "2027 Global Markets Graduate Analyst", G, "Workday", d(2026,10,5), "Online assessment", "Assessment stage", d(2026,10,9), "Complete SHL assessment by 14/10", "09/10: invited to SHL online assessment"),
("Example Capital", HF, "Quantitative Researcher Internship", I, "Greenhouse", d(2026,10,2), "Applied", "Rejected", d(2026,10,8), "None", "08/10: not progressing"),
("Example Trading", TF, "Role not stated in email", U, "Direct", None, "Applied", "Check email", d(2026,9,30), "Open the 30/09 email to confirm outcome", "Update received; outcome unclear"),
]
R.sort(key=lambda r: (r[5] or r[8]), reverse=True)

STAT = ["Awaiting response","Assessment stage","Interview","Offer","Rejected","Closed","Closed by employer","No response","Not submitted","Check email"]
FIRMS = [IB, BIB, HF, TF, PE, AM, FT, DATA, EN, PS, TECH, OTH]
F = "Arial"
thin = Side(style="thin", color="D0D0D0"); B = Border(left=thin, right=thin, top=thin, bottom=thin)
HDR_FILL = PatternFill("solid", fgColor="1F3864")
def hdr(c): c.font = Font(name=F, bold=True, color="FFFFFF"); c.fill = HDR_FILL; c.alignment = Alignment(vertical="center", wrap_text=True)

wb = Workbook(); ws = wb.active; ws.title = "Applications"
H = ["Company","Firm type","Role","Programme","Applied via","Date applied","Furthest stage","Status","Last update","Days since update","Next step","Notes"]
ws.append(H)
for i, r in enumerate(R, start=2):
    co, ft, role, prog, via, applied, stage, status, last, nxt, notes = r
    ws.append([co, ft, role, prog, via, applied if applied else "Not in emails", stage, status, last,
               f'=IF(ISNUMBER(I{i}),TODAY()-I{i},"")', nxt, notes])
n = len(R) + 1
for c in ws[1]: hdr(c)
for row in ws.iter_rows(min_row=2, max_row=n):
    for c in row:
        c.font = Font(name=F, size=10); c.border = B; c.alignment = Alignment(vertical="top", wrap_text=True)
    row[5].number_format = "dd/mm/yyyy"; row[8].number_format = "dd/mm/yyyy"; row[9].number_format = "0"
    row[9].alignment = Alignment(vertical="top", horizontal="center")
    if row[5].value == "Not in emails": row[5].font = Font(name=F, size=10, italic=True, color="808080")
    if row[10].value == "None": row[10].font = Font(name=F, size=10, color="A0A0A0")
for col, w in zip("ABCDEFGHIJKL", [22, 22, 42, 12, 18, 13, 20, 18, 12, 11, 34, 46]): ws.column_dimensions[col].width = w
ws.freeze_panes = "B2"; ws.row_dimensions[1].height = 30
tab = Table(displayName="Applications", ref=f"A1:L{n}")
tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
ws.add_table(tab)

for col, opts in (("H", STAT), ("B", FIRMS), ("D", [G, I, U])):
    dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
    ws.add_data_validation(dv); dv.add(f"{col}2:{col}{n+200}")
colors = {"Rejected":"F8D7DA","Closed":"E2E3E5","Closed by employer":"E2E3E5","Assessment stage":"FFF3CD","Interview":"D1E7DD","Offer":"A3CFBB","Awaiting response":"DCEBFA","No response":"F2F2F2","Not submitted":"F2F2F2","Check email":"FFE5B4"}
for s, col in colors.items():
    ws.conditional_formatting.add(f"H2:H{n+200}", FormulaRule(formula=[f'$H2="{s}"'], fill=PatternFill("solid", fgColor=col)))
# flag stale active applications (awaiting / assessment) with no news for 21+ days
ws.conditional_formatting.add(f"J2:J{n+200}", FormulaRule(
    formula=[f'AND(ISNUMBER($J2),$J2>=21,OR($H2="Awaiting response",$H2="Assessment stage"))'],
    fill=PatternFill("solid", fgColor="FFE5B4"), font=Font(name=F, bold=True, color="9C5700")))

# ---------- Summary ----------
s = wb.create_sheet("Summary")
s["A1"] = "Job applications, 24 Jul - 24 Oct 2026"; s["A1"].font = Font(name=F, bold=True, size=14)

s["A3"] = "By status"; s["A3"].font = Font(name=F, bold=True, size=11)
s["A4"], s["B4"] = "Status", "Count"; hdr(s["A4"]); hdr(s["B4"])
for i, st in enumerate(STAT, start=5):
    s.cell(i, 1, st).font = Font(name=F)
    s.cell(i, 2, f'=COUNTIF(Applications!$H:$H,A{i})').font = Font(name=F)
t = 5 + len(STAT)
s.cell(t, 1, "Total").font = Font(name=F, bold=True)
s.cell(t, 2, f"=SUM(B5:B{t-1})").font = Font(name=F, bold=True)
s.cell(t+1, 1, "Still active (awaiting + assessment + interview + offer)").font = Font(name=F, size=10, italic=True)
s.cell(t+1, 2, f"=SUM(B5:B8)").font = Font(name=F, size=10, italic=True)

# by firm type
s["D3"] = "By firm type"; s["D3"].font = Font(name=F, bold=True, size=11)
heads = ["Firm type", "Applications", "Still active", "Rejected / closed", "Got past application"]
for j, h in enumerate(heads): hdr(s.cell(4, 4 + j, h))
for i, ft in enumerate(FIRMS, start=5):
    s.cell(i, 4, ft).font = Font(name=F)
    s.cell(i, 5, f'=COUNTIF(Applications!$B:$B,D{i})')
    s.cell(i, 6, f'=COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Awaiting response")+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Assessment stage")+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Interview")+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Offer")')
    s.cell(i, 7, f'=COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Rejected")+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Closed*")')
    s.cell(i, 8, f'=SUMPRODUCT((Applications!$B$2:$B${n+200}=D{i})*(Applications!$G$2:$G${n+200}<>"Applied")*(Applications!$G$2:$G${n+200}<>"Started")*(Applications!$G$2:$G${n+200}<>""))')
    for j in range(5, 9): s.cell(i, j).font = Font(name=F); s.cell(i, j).alignment = Alignment(horizontal="center")
ft_end = 4 + len(FIRMS)
s.cell(ft_end+1, 4, "Total").font = Font(name=F, bold=True)
for j, col in zip(range(5, 9), "EFGH"):
    c = s.cell(ft_end+1, j, f"=SUM({col}5:{col}{ft_end})"); c.font = Font(name=F, bold=True); c.alignment = Alignment(horizontal="center")

# by programme
p0 = t + 4
s.cell(p0, 1, "By programme").font = Font(name=F, bold=True, size=11)
hdr(s.cell(p0+1, 1, "Programme")); hdr(s.cell(p0+1, 2, "Count"))
for k, pg in enumerate([G, I, U], start=p0+2):
    s.cell(k, 1, pg).font = Font(name=F)
    s.cell(k, 2, f'=COUNTIF(Applications!$D:$D,A{k})').font = Font(name=F)

# notes
nr = max(ft_end + 4, p0 + 7)
notes = ["Notes",
 "Source: your Outlook inbox and sent items, searched for 'application', 'interview', 'unfortunately' and 'applying'.",
 "'Date applied' is the date of the confirmation email; 'Not in emails' means only an outcome email was found.",
 "'Furthest stage' is the furthest point reached, even if later rejected. 'Got past application' counts anything beyond Applied.",
 "'Days since update' turns amber when an active application has had no news for 21+ days.",
 "'Unconfirmed' firm type: Circeus, Mondrian Alpha, ANL and the unnamed GRB role couldn't be identified for certain.",
 "Left out: UCL MSc applications, BCG event registration, job alerts and recruiter marketing emails.",
 "Firm type, Programme and Status have drop-downs, so you can keep the sheet updated yourself."]
for j, tx in enumerate(notes):
    s.cell(nr + j, 1, tx).font = Font(name=F, bold=(j == 0), size=10, italic=(j > 0))
s.column_dimensions["A"].width = 30; s.column_dimensions["B"].width = 9; s.column_dimensions["C"].width = 3
s.column_dimensions["D"].width = 24
for col in "EFGH": s.column_dimensions[col].width = 14
s.row_dimensions[4].height = 30
import sys
wb.save(sys.argv[1] if len(sys.argv) > 1 else "Job_Applications_Tracker_example.xlsx")
print(len(R))

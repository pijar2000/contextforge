"""Writes the binary sample documents (DOCX and PDF). All content is fictional."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docx import Document  # noqa: E402

from contextforge.devtools.minipdf import build_pdf  # noqa: E402

OUT = ROOT / "datasets" / "sample_documents"


def firmware_spec() -> Document:
    doc = Document()
    doc.add_heading("HX-200 Controller Firmware Update Specification", level=0)
    doc.add_heading("Signing", level=1)
    doc.add_paragraph(
        "Every firmware image is signed with Ed25519. The controller rejects any image whose "
        "signature does not verify against the public key stored in secure memory."
    )
    doc.add_heading("Staged rollout", level=1)
    doc.add_paragraph(
        "Updates are released to 5 percent of the fleet first, then 25 percent, then 100 percent. "
        "Each stage soaks for 24 hours before the next one starts."
    )
    doc.add_paragraph("Rollout stops automatically if the failure rate exceeds 1 percent.", style="List Bullet")
    doc.add_paragraph("A stopped rollout can only be resumed by the release manager.", style="List Bullet")
    doc.add_heading("Image limits", level=1)
    table = doc.add_table(rows=3, cols=2)
    for row, (a, b) in zip(table.rows, [("Parameter", "Limit"), ("Maximum image size", "48 MB"),
                                        ("Download timeout", "120 seconds")], strict=True):
        row.cells[0].text, row.cells[1].text = a, b
    return doc


def supplier_onboarding() -> Document:
    doc = Document()
    doc.add_heading("Supplier Onboarding Procedure", level=0)
    doc.add_heading("Qualification", level=1)
    doc.add_paragraph(
        "Every new supplier completes the security questionnaire and provides proof of ISO 9001 "
        "certification before the first purchase order."
    )
    doc.add_heading("Approval", level=1)
    doc.add_paragraph(
        "Procurement and Legal both approve a new supplier. Suppliers handling personal data also "
        "need a signed data processing agreement."
    )
    doc.add_heading("Payment terms", level=1)
    doc.add_paragraph(
        "The standard payment terms for new suppliers are net 45 days from the invoice date. "
        "Early payment discounts require approval from Finance."
    )
    return doc


MAINTENANCE = [
    [("h1", "HX-200 Maintenance Guide"),
     ("h2", "Maintenance schedule"),
     ("p", "Inspect the hydraulic seals every 500 operating hours. Replace any seal that shows "
           "cracking or fluid residue. Record each inspection in the asset log."),
     ("p", "Clean the finger pads weekly with isopropyl alcohol.")],
    [("h2", "Fluid replacement"),
     ("p", "Replace the hydraulic fluid every 2,000 operating hours. Use ISO VG 32 fluid only; "
           "mixing fluid grades damages the seals."),
     ("p", "Drain the reservoir completely, refill to the marked level and bleed the line at 6.5 bar.")],
    [("h2", "Troubleshooting"),
     ("p", "If the gripper slips or loses grip on a load, first check the supply pressure. It must "
           "read 6.5 bar. Low pressure usually points to a worn pump or an air bubble in the line."),
     ("p", "If the fingers move slowly in cold conditions, warm the unit above -10 degrees Celsius.")],
]

BATTERY = [
    [("h1", "Battery Degradation Study 2025"),
     ("h2", "Methodology"),
     ("p", "We cycled 48 lithium iron phosphate cells at three ambient temperatures: 15, 25 and 45 "
           "degrees Celsius. Each cell was charged at 0.5C and discharged at 1C.")],
    [("h2", "Results"),
     ("p", "At 25 degrees Celsius the cells retained 92 percent of their capacity after 1,000 "
           "cycles. At 45 degrees Celsius the retention fell to 81 percent."),
     ("p", "Elevated temperature accelerated ageing in every test group, with the strongest "
           "effect after 500 cycles.")],
    [("h2", "Recommendations"),
     ("p", "Keep battery enclosures below 35 degrees Celsius during charging. A passive heat "
           "spreader was sufficient in the pilot units.")],
]


def main() -> None:
    (OUT / "engineering").mkdir(parents=True, exist_ok=True)
    firmware_spec().save(OUT / "engineering" / "firmware-update-spec.docx")
    supplier_onboarding().save(OUT / "operations" / "supplier-onboarding.docx")
    (OUT / "product" / "hx200-maintenance-guide.pdf").write_bytes(
        build_pdf(MAINTENANCE, header="Halvorsen Robotics - Internal")
    )
    (OUT / "research" / "battery-degradation-study.pdf").write_bytes(
        build_pdf(BATTERY, header="Halvorsen Robotics - Research Office")
    )
    print("sample documents written to", OUT)


if __name__ == "__main__":
    main()

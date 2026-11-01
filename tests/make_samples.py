"""Generate the sample PDFs used by the demo and tests.

Run from the project root:

    python -m tests.make_samples
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUTPUT_DIR = Path(__file__).resolve().parent / "sample_documents"

SAMPLES: dict[str, tuple[str, list[str]]] = {
    "electricity_bill": (
        "BANGALORE ELECTRICITY SUPPLY COMPANY LIMITED",
        [
            "(A Government of Karnataka Undertaking)",
            "Electricity Bill / Tax Invoice",
            "",
            "Bill Date: 28/10/2026",
            "Invoice No: BESCOM/2026/004521",
            "Consumer No: 4050 1234 567",
            "Billing Period: 28/09/2026 to 27/10/2026",
            "Due Date: 06/11/2026",
            "",
            "Customer Name: Akshaya Rao",
            "Address: 42, 3rd Cross, Indiranagar, Bengaluru 560038",
            "",
            "Units Consumed: 312 kWh",
            "Tariff: Domestic LT-1",
            "Energy Charges: Rs. 1,850.00",
            "Fixed Charges: Rs. 120.00",
            "Electricity Tax: Rs. 188.75",
            "Arrears: Rs. 0.00",
            "",
            "Total Amount Due: Rs. 2,158.75",
            "",
            "Pay by 06/11/2026 to avoid disconnection.",
            "For billing queries call 1912 or visit bescom.karnataka.gov.in",
        ],
    ),
    "warranty_card": (
        "AQUACARE HOME APPLIANCES PRIVATE LIMITED",
        [
            "Warranty Card",
            "",
            "Product Name: AquaPure RO Water Purifier",
            "Model: AP-RO-7L",
            "Serial Number: AQ2026RO778812",
            "Warranty Number: WC-2026-778812",
            "Purchase Date: 12/08/2026",
            "Warranty Period: 24 months",
            "Expiry Date: 11/08/2028",
            "",
            "Purchased From: AquaCare Experience Store",
            "Customer Name: Akshaya Rao",
            "Invoice No: AC/2026/1187",
            "Purchase Price: Rs. 14,999.00",
            "",
            "This product is guaranteed against manufacturing defects.",
            "Warranty is valid only with this card and the original invoice.",
            "Service centre: 1800-123-4567",
        ],
    ),
    "rental_agreement": (
        "RENTAL AGREEMENT",
        [
            "",
            "This Rental Agreement is made on 01/04/2026 between:",
            "",
            "Lessor: Mr. Ramesh Kumar, residing at 18, Jayanagar, Bengaluru.",
            "Lessee: Ms. Akshaya Rao, residing at 42, Indiranagar, Bengaluru.",
            "",
            "Property Address: 7B, Lakeview Apartments, Koramangala, Bengaluru 560034",
            "Monthly Rent: Rs. 28,000.00",
            "Security Deposit: Rs. 1,12,000.00",
            "Notice Period: 2 months",
            "",
            "Start Date: 01/05/2026",
            "End Date: 30/04/2027",
            "Renewal Date: 15/04/2027",
            "",
            "The Lessee shall pay the monthly rent on or before the 5th day of every month.",
            "The Tenant must give 2 months notice before terminating the agreement.",
            "The agreement shall renew before 15/04/2027 unless either party gives notice.",
            "The Lessor is responsible for major structural repairs.",
            "",
            "Signed:",
            "Lessor: Mr. Ramesh Kumar",
            "Lessee: Ms. Akshaya Rao",
        ],
    ),
    "application_form": (
        "GOVERNMENT MODEL COLLEGE",
        [
            "APPLICATION FORM - POST GRADUATE ADMISSION 2026-27",
            "",
            "Application No: PGC/2026/009874",
            "Applicant Name: Akshaya Rao",
            "Father's Name: Suresh Rao",
            "Mother's Name: Lakshmi Rao",
            "Date of Birth: 14/06/2003",
            "Gender: Female",
            "Address: 42, 3rd Cross, Indiranagar, Bengaluru 560038",
            "",
            "Submission Date: 30/11/2026",
            "",
            "Documents Required:",
            "1. Class 10 and 12 marksheets",
            "2. Bachelor's degree certificate",
            "3. Transfer certificate",
            "4. Aadhaar card copy",
            "5. Passport-size photographs",
            "",
            "Declaration",
            "I hereby declare that the information provided above is true.",
            "Signature of Applicant: __________",
        ],
    ),
}


def _write_pdf(path: Path, title: str, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(55, y, title)
    y -= 26
    pdf.setFont("Helvetica", 10)
    for line in lines:
        if y < 55:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = height - 55
        pdf.drawString(55, y, line)
        y -= 16
    pdf.save()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (title, lines) in SAMPLES.items():
        pdf_path = OUTPUT_DIR / f"{name}.pdf"
        _write_pdf(pdf_path, title, lines)
        text_path = OUTPUT_DIR / f"{name}.txt"
        text_path.write_text("\n".join([title, *lines]) + "\n", encoding="utf-8")
        print(f"Created {pdf_path.name} and {text_path.name}")


if __name__ == "__main__":
    main()

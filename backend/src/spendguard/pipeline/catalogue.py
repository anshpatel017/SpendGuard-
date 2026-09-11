"""Reference data for the synthetic INR procurement generator.

Data only - no logic. Kept separate from ``synthetic.py`` so the realism
choices (what a department buys, what a cement bag costs) can be read and
challenged without wading through generation code.

Prices are indicative Indian public-procurement rates in rupees, inclusive of
tax. They only need to be *plausible and internally consistent*: detectors
compare transactions against each other, never against these numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    base_price: float  # INR per unit
    qty_min: int
    qty_max: int
    recurring: bool = False  # billed as a fixed monthly contract, never ad hoc


@dataclass(frozen=True)
class Category:
    name: str
    group: str  # related categories a supplier may also serve
    items: tuple[Item, ...]
    trade_words: tuple[str, ...]  # what suppliers in this trade call themselves
    market_weight: float  # share of suppliers operating in this category
    price_sigma: float = 0.08  # lognormal spread of legitimate unit prices
    round_to: float = 0.01  # services are priced in round figures; goods are not

    @property
    def regular_items(self) -> tuple[Item, ...]:
        return tuple(i for i in self.items if not i.recurring)

    @property
    def recurring_items(self) -> tuple[Item, ...]:
        return tuple(i for i in self.items if i.recurring)


@dataclass(frozen=True)
class Department:
    code: str
    name: str
    activity: float  # relative purchasing volume
    n_officers: int
    categories: tuple[str, ...]  # what it buys, most frequent first


CATEGORIES: tuple[Category, ...] = (
    Category(
        "Office Stationery",
        "paper",
        (
            Item("A4 Paper Ream 75 GSM", 290, 10, 200),
            Item("Ball Pens Box of 50", 400, 2, 40),
            Item("File Folders Pack of 100", 1_200, 1, 20),
            Item("Stapler Heavy Duty", 650, 1, 15),
            Item("Toner Cartridge", 3_800, 1, 20),
        ),
        ("Stationers", "Traders", "Enterprises", "Paper Mart", "Office Supplies"),
        1.4,
    ),
    Category(
        "Printing and Publication",
        "paper",
        (
            Item("Printed Forms per 1000", 1_800, 1, 50),
            Item("Flex Banners", 1_200, 2, 40),
            Item("Annual Report Printing", 95_000, 1, 1),
        ),
        ("Printers", "Offset Press", "Graphics", "Enterprises"),
        0.7,
        round_to=10,
    ),
    Category(
        "Books and Educational Material",
        "paper",
        (
            Item("School Textbooks", 220, 50, 3_000),
            Item("Library Books", 650, 10, 300),
            Item("Science Educational Kit", 4_200, 5, 100),
        ),
        ("Book House", "Book Depot", "Publishers", "Traders"),
        0.6,
    ),
    Category(
        "Computer Hardware",
        "it",
        (
            Item("Desktop Computer Core i5", 52_000, 1, 25),
            Item("Laptop Core i5 14 inch", 62_000, 1, 15),
            Item("LED Monitor 24 inch", 11_500, 1, 30),
            Item("Laser Printer", 18_500, 1, 10),
            Item("UPS 1 kVA", 6_800, 1, 20),
        ),
        ("Computers", "Infotech", "Systems", "Technologies", "Enterprises"),
        1.2,
    ),
    Category(
        "Networking Equipment",
        "it",
        (
            Item("Network Switch 24 Port", 14_500, 1, 10),
            Item("WiFi Access Point", 7_200, 1, 25),
            Item("CAT6 Cable Box 305m", 9_800, 1, 15),
        ),
        ("Networks", "Infotech", "Systems", "Solutions"),
        0.6,
    ),
    Category(
        "IT Services",
        "it",
        (
            Item("Software AMC Quarterly", 85_000, 1, 1),
            Item("Data Entry Services per 1000 Records", 1_500, 5, 100),
            Item("Website Maintenance", 25_000, 1, 1, recurring=True),
        ),
        ("Infotech", "Software Solutions", "Technologies", "Digital Services"),
        0.6,
        round_to=100,
    ),
    Category(
        "Furniture",
        "furniture",
        (
            Item("Ergonomic Office Chair", 8_500, 1, 40),
            Item("Steel Almirah", 14_000, 1, 15),
            Item("Workstation Table", 11_000, 1, 30),
            Item("Conference Table 10 Seater", 48_000, 1, 3),
        ),
        ("Furniture", "Furnishers", "Steel Industries", "Interiors"),
        0.8,
    ),
    Category(
        "Cleaning and Sanitation",
        "facilities",
        (
            Item("Floor Cleaner 5 Litre", 450, 5, 100),
            Item("Hand Sanitizer 5 Litre", 900, 2, 60),
            Item("Garbage Bags Pack", 250, 10, 200),
            Item("Mop Set", 600, 2, 40),
        ),
        ("Hygiene Products", "Chemicals", "Traders", "Suppliers"),
        0.8,
    ),
    Category(
        "Housekeeping Services",
        "facilities",
        (Item("Housekeeping Services", 95_000, 1, 1, recurring=True),),
        ("Facility Services", "Facility Management", "Services"),
        0.35,
        round_to=1_000,
    ),
    Category(
        "Security Services",
        "security",
        (Item("Security Guard Services", 145_000, 1, 1, recurring=True),),
        ("Security Services", "Security Agency", "Guarding Solutions"),
        0.35,
        round_to=1_000,
    ),
    Category(
        "Electrical Fittings",
        "works",
        (
            Item("LED Tube Light 20W", 320, 10, 300),
            Item("Ceiling Fan", 2_400, 2, 60),
            Item("MCB 32A", 380, 5, 100),
            Item("Copper Wire 2.5 sq mm 90m", 3_200, 1, 40),
        ),
        ("Electricals", "Electric Works", "Traders", "Enterprises"),
        1.0,
    ),
    Category(
        "Plumbing and Water Supply",
        "works",
        (
            Item("PVC Pipe 110mm 6m", 1_250, 5, 200),
            Item("Water Meter", 2_100, 2, 100),
            Item("Submersible Pump 1 HP", 14_500, 1, 10),
        ),
        ("Pipes and Fittings", "Hydraulics", "Engineering Works", "Traders"),
        0.7,
    ),
    Category(
        "Civil Works Material",
        "works",
        (
            Item("Cement Bag 50kg OPC", 410, 50, 2_000),
            Item("TMT Steel Bar per Quintal", 6_200, 5, 200),
            Item("River Sand per Cubic Metre", 1_800, 5, 150),
            Item("Bricks per 1000", 7_500, 1, 50),
        ),
        ("Constructions", "Builders", "Building Materials", "Infra Projects"),
        1.0,
    ),
    Category(
        "Medical Consumables",
        "health",
        (
            Item("Surgical Gloves Box of 100", 420, 10, 300),
            Item("Disposable Syringes Box of 100", 650, 5, 200),
            Item("N95 Masks Box of 20", 900, 5, 150),
            Item("Absorbent Cotton Roll 500g", 180, 20, 400),
        ),
        ("Medicals", "Surgicals", "Healthcare", "Medical Agencies"),
        1.0,
    ),
    Category(
        "Pharmaceuticals",
        "health",
        (
            Item("Paracetamol 500mg Strip of 10", 22, 500, 20_000),
            Item("Amoxicillin 500mg Strip of 10", 95, 200, 8_000),
            Item("ORS Sachets", 18, 500, 20_000),
        ),
        ("Pharma", "Pharmaceuticals", "Drug House", "Medical Agencies"),
        0.8,
    ),
    Category(
        "Laboratory Equipment",
        "health",
        (
            Item("Digital Microscope", 38_000, 1, 5),
            Item("Laboratory Centrifuge", 65_000, 1, 3),
            Item("pH Meter", 9_500, 1, 10),
        ),
        ("Scientific", "Lab Instruments", "Scientific Traders"),
        0.5,
    ),
    Category(
        "Vehicle Maintenance",
        "transport",
        (
            Item("Vehicle Periodic Servicing", 6_500, 1, 6),
            Item("Tyre Replacement", 7_800, 1, 8),
            Item("Battery Replacement", 5_400, 1, 6),
        ),
        ("Motors", "Automobiles", "Auto Works", "Garage"),
        0.7,
        round_to=10,
    ),
    Category(
        "Fuel",
        "transport",
        (
            Item("Diesel per Litre", 92, 100, 3_000),
            Item("Petrol per Litre", 103, 50, 1_500),
        ),
        ("Fuels", "Petroleum", "Filling Station", "Service Station"),
        0.5,
        price_sigma=0.03,
    ),
    Category(
        "Catering and Hospitality",
        "hospitality",
        (
            Item("Meeting Refreshments per Head", 180, 20, 400),
            Item("Event Catering", 45_000, 1, 1),
        ),
        ("Caterers", "Hospitality", "Foods", "Restaurant"),
        0.6,
        round_to=10,
    ),
    Category(
        "Training and Consultancy",
        "services",
        (
            Item("Training Programme per Participant", 3_500, 10, 80),
            Item("Consultancy Services", 175_000, 1, 1),
        ),
        ("Consultants", "Management Services", "Advisory", "Academy"),
        0.5,
        round_to=100,
    ),
    Category(
        "Uniforms and Textiles",
        "textiles",
        (
            Item("Staff Uniform Set", 1_450, 10, 300),
            Item("Hospital Bedsheets", 380, 20, 500),
        ),
        ("Textiles", "Garments", "Tailors", "Fabrics"),
        0.6,
    ),
    Category(
        "Agricultural Inputs",
        "agriculture",
        (
            Item("Certified Seeds per kg", 240, 50, 2_000),
            Item("Fertilizer Bag 50kg", 1_350, 20, 600),
            Item("Pesticide per Litre", 650, 10, 300),
        ),
        ("Agro", "Agro Industries", "Krishi Kendra", "Seeds Corporation"),
        0.7,
    ),
)

CATEGORIES_BY_NAME: dict[str, Category] = {c.name: c for c in CATEGORIES}

# Every department also buys these occasionally.
GENERAL_CATEGORIES: tuple[str, ...] = ("Office Stationery", "Cleaning and Sanitation")

DEPARTMENTS: tuple[Department, ...] = (
    Department(
        "PWD",
        "Public Works",
        1.6,
        7,
        (
            "Civil Works Material",
            "Electrical Fittings",
            "Plumbing and Water Supply",
            "Furniture",
            "Vehicle Maintenance",
            "Fuel",
        ),
    ),
    Department(
        "HLT",
        "Health",
        1.5,
        7,
        (
            "Medical Consumables",
            "Pharmaceuticals",
            "Laboratory Equipment",
            "Cleaning and Sanitation",
            "Uniforms and Textiles",
        ),
    ),
    Department(
        "EDU",
        "Education",
        1.3,
        6,
        (
            "Books and Educational Material",
            "Furniture",
            "Computer Hardware",
            "Office Stationery",
            "Catering and Hospitality",
        ),
    ),
    Department(
        "ITD",
        "Information Technology",
        1.0,
        4,
        ("Computer Hardware", "Networking Equipment", "IT Services", "Electrical Fittings"),
    ),
    Department(
        "ADM",
        "General Administration",
        1.2,
        6,
        (
            "Office Stationery",
            "Furniture",
            "Catering and Hospitality",
            "Printing and Publication",
            "Vehicle Maintenance",
            "Fuel",
        ),
    ),
    Department(
        "WSD",
        "Water Supply and Sanitation",
        1.0,
        5,
        (
            "Plumbing and Water Supply",
            "Civil Works Material",
            "Electrical Fittings",
            "Vehicle Maintenance",
            "Fuel",
        ),
    ),
    Department(
        "TRN",
        "Transport",
        0.8,
        4,
        ("Vehicle Maintenance", "Fuel", "Uniforms and Textiles", "Printing and Publication"),
    ),
    Department(
        "FIN",
        "Finance",
        0.6,
        4,
        (
            "Office Stationery",
            "Computer Hardware",
            "Printing and Publication",
            "Training and Consultancy",
        ),
    ),
    Department(
        "AGR",
        "Agriculture",
        0.9,
        5,
        (
            "Agricultural Inputs",
            "Vehicle Maintenance",
            "Fuel",
            "Training and Consultancy",
            "Printing and Publication",
        ),
    ),
    Department(
        "POL",
        "Police",
        1.1,
        6,
        (
            "Uniforms and Textiles",
            "Vehicle Maintenance",
            "Fuel",
            "Computer Hardware",
            "Networking Equipment",
        ),
    ),
    Department(
        "REV",
        "Revenue",
        0.7,
        4,
        ("Office Stationery", "Printing and Publication", "Computer Hardware", "Furniture"),
    ),
    Department(
        "UDD",
        "Urban Development",
        1.0,
        5,
        (
            "Civil Works Material",
            "Electrical Fittings",
            "Plumbing and Water Supply",
            "Training and Consultancy",
            "Cleaning and Sanitation",
        ),
    ),
)

# Supplier name stems: family names and the devotional / aspirational words
# Indian trading firms commonly trade under.
SURNAMES: tuple[str, ...] = (
    "Sharma", "Patel", "Reddy", "Gupta", "Iyer", "Nair", "Singh", "Verma", "Agarwal",
    "Joshi", "Mehta", "Shah", "Rao", "Kulkarni", "Desai", "Chauhan", "Yadav", "Mishra",
    "Pandey", "Banerjee", "Mukherjee", "Das", "Ghosh", "Pillai", "Menon", "Bhat", "Naidu",
    "Kapoor", "Malhotra", "Saxena", "Trivedi", "Jain", "Bansal", "Goyal", "Khanna",
    "Chopra", "Sethi", "Bhatia", "Rathore", "Solanki",
)  # fmt: skip

FIRM_WORDS: tuple[str, ...] = (
    "Shree Ganesh", "Om Sai", "Bharat", "National", "Deccan", "Sunrise", "Galaxy",
    "Pioneer", "Laxmi", "Balaji", "Jai Hind", "Maruti", "Kaveri", "Narmada", "Himalaya",
    "Sahyadri", "Vishwakarma", "Annapurna", "Global", "Metro", "Royal", "Supreme",
    "Unique", "Apex", "Zenith", "Pragati", "Samarth", "Siddhi", "Shakti", "Arihant",
)  # fmt: skip

# (suffix, probability). An empty suffix means a proprietorship with no legal form.
LEGAL_SUFFIXES: tuple[tuple[str, float], ...] = (
    ("Pvt Ltd", 0.28),
    ("Private Limited", 0.12),
    ("LLP", 0.06),
    ("& Co", 0.08),
    ("& Sons", 0.06),
    ("", 0.40),
)

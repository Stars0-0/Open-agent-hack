"""Generate SYNTHETIC claims for three separate insurers plus shop, address and vehicle directories.

Plants one fraud ring (14 claims, 9 people, 3 vehicles, 1 shop) and innocent look-alikes:
 - an apartment block (40 units) where 6 unrelated people share an address
 - a family sharing one phone
 - a very busy repair shop used by many unrelated people
 - a near-ring: 3 unrelated claims at one small shop with nothing else in common
Writes CSVs to data/sample/ and the truth to data/ground_truth.json (tests only; the agent never reads it).
All names, phones and addresses are fictional. Usage: python scripts/make_ring_data.py [seed]
"""
import csv
import json
import os
import random
import sys

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
FIRST = ["Aaron", "Bria", "Carlos", "Dana", "Elan", "Farah", "Gavin", "Hana", "Isaac", "Jada", "Kyle", "Lena", "Marcus",
         "Nia", "Omar", "Priya", "Quinn", "Rohan", "Sasha", "Troy", "Uma", "Victor", "Wendy", "Xavier", "Yara", "Zane"]
LAST = ["Alleyne", "Baptiste", "Chen", "Dookhan", "Edwards", "Ferreira", "Gopaul", "Henry", "Ince", "Joseph", "Khan",
        "Lewis", "Mohammed", "Narine", "Ollivierre", "Persad", "Quamina", "Ramkissoon", "Seecharan", "Thomas", "Updike",
        "Valdez", "Williams", "Yearwood", "Zephyr"]
RING_LAST = ["Brathwaite", "Cumberbatch", "Delgado", "Encarnacion", "Fontaine", "Gaspard", "Harricharan", "Isidore", "Jaggernauth"]
INSURERS = ["A", "B", "C"]
COLS = ["claim_id", "claimant_name", "phone", "address", "vin", "shop_id", "claim_date", "amount", "narrative"]


def build(seed: int = 11):
    rng = random.Random(seed)
    claims = {i: [] for i in INSURERS}
    counter = {i: 0 for i in INSURERS}
    used_names, used_phones = set(), set()

    def uniq_phone():
        while True:
            p = f"868-{rng.randint(300, 799)}-{rng.randint(1000, 9999)}"
            if p not in used_phones:
                used_phones.add(p)
                return p

    def add(ins, name, phone, address, vin, shop, amount=None, narrative="Rear-end collision at junction."):
        counter[ins] += 1
        cid = f"{ins}{counter[ins]:04d}"
        claims[ins].append([cid, name, phone, address, vin, shop, f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)}",
                            amount if amount is not None else round(rng.uniform(900, 9000), 2), narrative])
        return cid

    def legit_name():
        while True:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if n not in used_names:
                used_names.add(n)
                return n

    shops = [["S01", "Quickfix Auto Body", "5 Industrial Estate, Chaguanas", "868-555-0100", "R. Brathwaite"],
             ["S02", "Central Motors", "88 Southern Main Rd, San Fernando", "868-555-0101", "L. Singh"],
             ["S03", "Port Bodyworks", "14 Wrightson Rd, Port of Spain", "868-555-0102", "M. Joseph"],
             ["S04", "Valsayn Auto Care", "3 Churchill Roosevelt Hwy", "868-555-0103", "A. Khan"],
             ["S05", "Tony's Garage", "21 Eastern Main Rd, Arima", "868-555-0104", "T. Gomez"],
             ["S06", "Westside Collision", "9 Western Main Rd, Diego Martin", "868-555-0105", "K. Lewis"],
             ["S07", "Couva Panel Works", "47 Southern Main Rd, Couva", "868-555-0106", "D. Ramdeen"],
             ["S08", "Sando Smash Repairs", "2 High St, San Fernando", "868-555-0107", "P. Ali"],
             ["S09", "Penal Auto Works", "70 Penal Rock Rd", "868-555-0108", "G. Baksh"],
             ["S10", "Chaguanas Body Shop", "19 Montrose Rd, Chaguanas", "868-555-0109", "N. Boodoo"],
             ["S11", "Point Fortin Autos", "33 Egret Dr, Point Fortin", "868-555-0110", "C. Marcano"]]
    busy_shop = "S02"
    addresses = [["Tower View Apartments, 1 Ariapita Ave", "apartment_block", 40]]
    legit_shops = ["S03", "S04", "S06", "S07", "S08", "S09", "S10", "S11"]
    street_no = [0]

    def house():  # every ordinary household gets its own address: coincidences must be planted, not accidental
        street_no[0] += 1
        return f"{street_no[0]} {rng.choice(['Eastern Main Rd', 'Southern Main Rd', 'Cipero St', 'Sangre Grande Rd', 'Mucurapo Rd'])}"

    # innocent apartment block: 6 unrelated people share one address
    block = addresses[0][0]
    for _ in range(6):
        add(rng.choice(INSURERS), legit_name(), uniq_phone(), block, f"VIN{rng.randint(10**8, 10**9)}", rng.choice(legit_shops))
    # innocent family: one phone, one surname, three people
    fam_phone = uniq_phone()
    for first in ["Ravi", "Anita", "Dev"]:
        used_names.add(f"{first} Ramkissoon")
        add(rng.choice(INSURERS), f"{first} Ramkissoon", fam_phone, house(), f"VIN{rng.randint(10**8, 10**9)}", rng.choice(legit_shops))
    # near-ring: 3 unrelated claims at a small shop, nothing else in common
    for _ in range(3):
        add(rng.choice(INSURERS), legit_name(), uniq_phone(), house(), f"VIN{rng.randint(10**8, 10**9)}", "S05")
    # ordinary background claims; the busy shop takes ~35%
    for ins in INSURERS:
        for _ in range(95):
            n = legit_name()
            addr = house()
            addresses.append([addr, "house", 1])
            roll = rng.random()
            shop = busy_shop if roll < 0.35 else "S01" if roll < 0.38 else "S05" if roll < 0.40 else rng.choice(legit_shops)
            add(ins, n, uniq_phone(), addr, f"VIN{rng.randint(10**8, 10**9)}", shop)
    # THE RING: 9 people, 14 claims, 3 vehicles, shop S01
    P = {i + 1: f"{rng.choice(FIRST)} {RING_LAST[i]}" for i in range(9)}
    x1, x2 = "868-555-0191", "868-555-0192"
    h1 = "12 Cunupia Rd"
    addresses.append([h1, "house", 1])
    for p in P.values():
        used_names.add(p)
    V1, V2, V3 = "VINRING0001", "VINRING0002", "VINRING0003"
    ring = [
        add("A", P[1], x1, "7 Mt Hope Rd", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("A", P[2], x1, "31 Bamboo Settlement", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("A", P[3], x1, "2 Debe Trace", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("A", P[4], x2, "90 Aranguez Rd", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("A", P[5], x2, h1, f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("A", P[1], x1, "7 Mt Hope Rd", V3, "S01"),
        add("B", P[6], x2, "55 Tacarigua Rd", V1, "S01"),
        add("B", P[5], uniq_phone(), h1, f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("B", P[4], x2, "90 Aranguez Rd", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("B", P[2], x1, "31 Bamboo Settlement", f"VIN{rng.randint(10**8, 10**9)}", "S01"),
        add("B", P[3], x1, "2 Debe Trace", V3, "S01"),
        add("C", P[7], uniq_phone(), "18 Penal Rock Rd", V1, "S01"),
        add("C", P[8], uniq_phone(), "6 Gasparillo Rd", V2, "S01"),
        add("C", P[9], uniq_phone(), "41 Moruga Rd", V2, "S01"),
    ]
    # narratives of ring claims share a template (what a long-context model would spot)
    for ins in INSURERS:
        for row in claims[ins]:
            if row[0] in ring:
                row[8] = "Vehicle struck while parked, third party fled, towed to shop same day."

    os.makedirs(os.path.join(OUT, "sample"), exist_ok=True)
    for old in os.listdir(os.path.join(OUT, "sample")):
        os.remove(os.path.join(OUT, "sample", old))

    def write(name, header, rows):
        with open(os.path.join(OUT, "sample", f"{name}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    for ins in INSURERS:
        write(f"insurer_{ins.lower()}_claims", COLS, claims[ins])
    write("repair_shops", ["shop_id", "name", "address", "phone", "owner"], shops)
    seen, uniq = set(), []
    for a in addresses:
        if a[0] not in seen:
            seen.add(a[0])
            uniq.append(a)
    write("address_directory", ["address", "kind", "unit_count"], uniq)
    all_rows = [r for ins in INSURERS for r in claims[ins]]
    write("vehicle_registry", ["vin", "registered_owner", "make"],
          [[r[4], r[1], rng.choice(["Toyota", "Nissan", "Suzuki", "Kia"])] for r in all_rows])
    truth = {"ring_claims": sorted(ring), "ring_people": sorted(P.values()), "ring_shop": "S01", "busy_shop": busy_shop,
             "apartment_block": block, "family_phone": fam_phone, "near_ring_shop": "S05",
             "ring_exposure": round(sum(r[7] for r in all_rows if r[0] in ring), 2), "total_claims": len(all_rows)}
    with open(os.path.join(OUT, "ground_truth.json"), "w") as f:
        json.dump(truth, f, indent=2)
    return truth


if __name__ == "__main__":
    t = build(int(sys.argv[1]) if len(sys.argv) > 1 else 11)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in t.items()}, indent=2))

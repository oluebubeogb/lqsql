import random, sqlite3, sys, datetime as dt
p = sys.argv[1]
c = sqlite3.connect(p)
c.executescript("""
DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS customers; DROP TABLE IF EXISTS events; DROP VIEW IF EXISTS big_orders;
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE, city TEXT, vip INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), total REAL, status TEXT, note TEXT, placed_at TEXT);
CREATE TABLE events (kind TEXT, payload TEXT, at TEXT);
CREATE INDEX idx_orders_status ON orders(status);
CREATE VIEW big_orders AS SELECT * FROM orders WHERE total > 400;
""")
cities = ["Lagos", "Abuja", "Enugu", "Ibadan", "Port Harcourt", "Kano"]
first = ["Ada", "Chidi", "Ngozi", "Tunde", "Bola", "Emeka", "Zainab", "Ife", "Uche", "Kemi"]
last = ["Okafor", "Adeyemi", "Bello", "Eze", "Okoro", "Balogun", "Musa", "Nwosu"]
random.seed(7)
for i in range(1, 241):
    n = f"{random.choice(first)} {random.choice(last)}"
    c.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)", (i, n, f"{n.split()[0].lower()}{i}@example.ng", random.choice(cities), int(random.random() < .15),
              (dt.datetime(2026, 1, 1) + dt.timedelta(hours=37 * i)).isoformat(sep=" ")))
for i in range(1, 1201):
    c.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)", (i, random.randint(1, 240), round(random.uniform(5, 600), 2), random.choice(["paid", "pending", "shipped", "refunded"]),
              None if random.random() < .7 else "gift wrap", (dt.datetime(2026, 3, 1) + dt.timedelta(minutes=97 * i)).isoformat(sep=" ")))
for i in range(60):
    c.execute("INSERT INTO events VALUES (?,?,?)", (random.choice(["login", "logout", "view"]), '{"ok": true}', dt.datetime.now().isoformat()))
c.commit()
print("seeded", p)

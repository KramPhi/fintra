from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
import sqlite3
import os
from collections import defaultdict
import csv
import io
from datetime import datetime
import math

app = Flask(__name__)
app.secret_key = 'your_secret_key'

DB_PATH = os.path.join(os.path.dirname(__file__), 'db', 'tracker.db')

def init_db():
    os.makedirs("db", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            date TEXT,
            type TEXT,
            category TEXT,
            amount REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS finance_items (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            item_type TEXT CHECK(item_type IN ('asset', 'liability')),
            name TEXT,
            value REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS net_worth_history (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            date TEXT,
            net_worth REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            goal_amount REAL,
            target_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/set_goal', methods=['POST'])
def set_goal():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    goal_amount = float(request.form['goal_amount'])
    target_date = request.form['target_date']

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM goals WHERE user_id=?", (session['user_id'],))
    c.execute("INSERT INTO goals (user_id, goal_amount, target_date) VALUES (?, ?, ?)",
              (session['user_id'], goal_amount, target_date))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete_goal')
def delete_goal():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM goals WHERE user_id=?", (session['user_id'],))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    from pytz import timezone
    import pytz

    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Default to Philippine time (Asia/Manila)
    ph_tz = timezone('Asia/Manila')
    us_tz = timezone('US/Eastern')
    user_agent = request.headers.get('User-Agent', '').lower()
    now = datetime.now(ph_tz)

    # Simple detection logic for US vs PH (adjust as needed)
    if any(loc in user_agent for loc in ['windows', 'macintosh', 'iphone']):
        now = datetime.now(us_tz)

    formatted_date = now.strftime('%B %d, %Y')
    formatted_time = now.strftime('%I:%M %p')
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT username FROM users WHERE id=?", (session['user_id'],))
    user = c.fetchone()

    c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC", (session['user_id'],))
    data = c.fetchall()

    c.execute("""
        SELECT
            SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END),
            SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END)
        FROM transactions WHERE user_id=?
    """, (session['user_id'],))
    income, expense = c.fetchone()
    income = income or 0
    expense = expense or 0
    total = income - expense

    c.execute("SELECT goal_amount FROM goals WHERE user_id=?", (session['user_id'],))
    goal_row = c.fetchone()
    goal = goal_row[0] if goal_row else None
    progress = (total / goal * 100) if goal else 0
    savings_rate = (income - expense) / income * 100 if income else 0

    # Forecast month to reach goal
    forecast_months = None
    if goal and income > expense:
        monthly_growth = income - expense
        if monthly_growth > 0:
            forecast_months = math.ceil((goal - total) / monthly_growth) if (goal - total) > 0 else 0

    conn.close()
    return render_template("index.html", transactions=data, username=user[0], user_id=session['user_id'],
                           total=total, goal=goal, progress=progress,
                           savings_rate=savings_rate, forecast_months=forecast_months,
                           current_date=formatted_date, current_time=formatted_time)

@app.route('/networth_chart')
def networth_chart():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT date, net_worth FROM net_worth_history WHERE user_id=? ORDER BY date", (session['user_id'],))
    history = c.fetchall()
    net_dates = [row[0] for row in history]
    net_values = [row[1] for row in history]

    # Forecast projection for the next 6 months
    projection = []
    if len(net_values) >= 2:
        growth = net_values[-1] - net_values[-2]
        last_date = datetime.strptime(net_dates[-1], "%Y-%m")
        for i in range(1, 7):
            next_date = (last_date.replace(day=1) + timedelta(days=32 * i)).strftime("%Y-%m")
            projected_value = net_values[-1] + (growth * i)
            net_dates.append(next_date)
            net_values.append(projected_value)

    conn.close()
    return render_template("networth_chart.html", net_dates=net_dates, net_values=net_values)

@app.route('/charts')
def charts():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT date, type, amount FROM transactions WHERE user_id=?", (session['user_id'],))
    rows = c.fetchall()
    monthly_data = defaultdict(lambda: {'income': 0, 'expense': 0})
    for row in rows:
        month = row[0][:7]
        monthly_data[month][row[1]] += row[2]

    months = sorted(monthly_data.keys())
    income_data = [monthly_data[m]['income'] for m in months]
    expense_data = [monthly_data[m]['expense'] for m in months]

    c.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='expense' GROUP BY category", (session['user_id'],))
    category_data = c.fetchall()
    categories = [row[0] for row in category_data]
    category_totals = [row[1] for row in category_data]

    conn.close()
    return render_template("charts.html", months=months, income_data=income_data,
                           expense_data=expense_data, categories=categories,
                           category_totals=category_totals)



@app.route('/finances', methods=['GET', 'POST'])
def finances():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        item_type = request.form['item_type']
        value = float(request.form['value'])
        c.execute("INSERT INTO finance_items (user_id, item_type, name, value) VALUES (?, ?, ?, ?)",
                  (session['user_id'], item_type, name, value))
        conn.commit()

    c.execute("SELECT name, value, id FROM finance_items WHERE user_id=? AND item_type='asset'", (session['user_id'],))
    assets = c.fetchall()
    c.execute("SELECT name, value, id FROM finance_items WHERE user_id=? AND item_type='liability'", (session['user_id'],))
    liabilities = c.fetchall()

    total_assets = sum([x[1] for x in assets])
    total_liabilities = sum([x[1] for x in liabilities])
    net_worth = total_assets - total_liabilities

    today = datetime.today().strftime("%Y-%m")
    c.execute("SELECT 1 FROM net_worth_history WHERE user_id=? AND date=?", (session['user_id'], today))
    if not c.fetchone():
        c.execute("INSERT INTO net_worth_history (user_id, date, net_worth) VALUES (?, ?, ?)",
                  (session['user_id'], today, net_worth))
        conn.commit()

    conn.close()
    return render_template("finances.html", assets=assets, liabilities=liabilities,
                           total_assets=total_assets, total_liabilities=total_liabilities,
                           net_worth=net_worth)


@app.route('/delete_item/<int:id>')
def delete_item(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM finance_items WHERE id=? AND user_id=?", (id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(url_for('finances'))






@app.route('/edit_item/<int:id>', methods=['GET', 'POST'])
def edit_item(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        value = float(request.form['value'])
        c.execute("UPDATE finance_items SET name=?, value=? WHERE id=? AND user_id=?",
                  (name, value, id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('finances'))

    c.execute("SELECT name, value FROM finance_items WHERE id=? AND user_id=?", (id, session['user_id']))
    item = c.fetchone()
    conn.close()
    if item:
        return render_template("edit_item.html", item=item, item_id=id)
    else:
        return "Item not found.", 404


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['user_id'] = user[0]
            return redirect(url_for('index'))
        else:
            return "Invalid credentials. Please try again."

    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        first_name = request.form['first_name']
        last_name = request.form['last_name']

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("""
                INSERT INTO users (username, password, email, first_name, last_name)
                VALUES (?, ?, ?, ?, ?)
            """, (username, password, email, first_name, last_name))
            conn.commit()
        except sqlite3.IntegrityError:
            return "Username or email already exists."
        conn.close()
        return redirect(url_for('login'))

    return render_template("register.html")


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    date = request.form['date']
    type_ = request.form['type']
    category = request.form['category']
    amount = float(request.form['amount'])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, date, type, category, amount) VALUES (?, ?, ?, ?, ?)",
              (session['user_id'], date, type_, category, amount))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete_transaction/<int:id>')
def delete_transaction(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/edit_transaction/<int:id>', methods=['GET', 'POST'])
def edit_transaction(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        date = request.form['date']
        type_ = request.form['type']
        category = request.form['category']
        amount = float(request.form['amount'])
        c.execute("""
            UPDATE transactions SET date=?, type=?, category=?, amount=?
            WHERE id=? AND user_id=?
        """, (date, type_, category, amount, id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    c.execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (id, session['user_id']))
    transaction = c.fetchone()
    conn.close()
    if transaction:
        return render_template("edit_transaction.html", transaction=transaction)
    else:
        return "Transaction not found.", 404


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        new_password = request.form.get('new_password')

        if new_password:
            c.execute("UPDATE users SET first_name=?, last_name=?, email=?, password=? WHERE id=?",
                      (first_name, last_name, email, new_password, session['user_id']))
        else:
            c.execute("UPDATE users SET first_name=?, last_name=?, email=? WHERE id=?",
                      (first_name, last_name, email, session['user_id']))

        conn.commit()

    c.execute("SELECT username, email, first_name, last_name FROM users WHERE id=?", (session['user_id'],))
    user = c.fetchone()
    conn.close()

    if user:
        return render_template("profile.html", user=user)
    else:
        return "User not found", 404


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='127.0.0.1', port=5000)

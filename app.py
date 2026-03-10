from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import json
import csv
from io import StringIO, BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Replace with a secure key in production
app.config['SESSION_COOKIE_SECURE'] = True  # Secure cookies for HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JS access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection

def init_db():
    with sqlite3.connect('users.db') as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, email TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, amount REAL, date TEXT, is_recurring INTEGER, recurrence_type TEXT, recurrence_interval INTEGER, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS income (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, source TEXT, amount REAL, date TEXT, is_recurring INTEGER, recurrence_type TEXT, recurrence_interval INTEGER, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, budget_limit REAL, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, name TEXT, target_amount REAL, current_amount REAL, due_date TEXT, FOREIGN KEY(username) REFERENCES users(username))')
    conn.close()

init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        with sqlite3.connect('users.db') as conn:
            try:
                conn.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)', (username, password, email))
                conn.commit()
                flash('Sign-up successful! Please sign in.', 'success')
                return redirect(url_for('signin'))
            except sqlite3.IntegrityError:
                flash('Username already exists!', 'error')
                return redirect(url_for('signup'))
    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect('users.db') as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
        if user:
            session['username'] = username
            session.permanent = True  # Session persists
            return redirect(url_for('dashboard'))
        flash('Invalid credentials!', 'error')
        return redirect(url_for('signin'))
    return render_template('signin.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        flash('Please sign in to access the dashboard.', 'error')
        return redirect(url_for('signin'))
    
    username = session['username']
    period = request.args.get('period', 'M').upper()

    with sqlite3.connect('users.db') as conn:
        # Fetch data
        expenses = conn.execute('SELECT category, amount, date, is_recurring, recurrence_type, recurrence_interval FROM expenses WHERE username = ?', (username,)).fetchall()
        income = conn.execute('SELECT source, amount, date, is_recurring, recurrence_type, recurrence_interval FROM income WHERE username = ?', (username,)).fetchall()
        categories = conn.execute('SELECT category FROM categories WHERE username = ?', (username,)).fetchall()
        budgets = conn.execute('SELECT category, budget_limit FROM budgets WHERE username = ?', (username,)).fetchall()
        goals = conn.execute('SELECT id, name, target_amount, current_amount, due_date FROM goals WHERE username = ?', (username,)).fetchall()

    # Process recurring transactions
    today = datetime.now()
    for exp in expenses:
        if exp[3]:  # is_recurring
            last_date = datetime.strptime(exp[2], '%Y-%m-%d')
            rec_type, interval = exp[4], exp[5]
            while last_date < today:
                if rec_type == 'daily':
                    last_date += timedelta(days=interval)
                elif rec_type == 'weekly':
                    last_date += timedelta(weeks=interval)
                elif rec_type == 'monthly':
                    last_date += timedelta(days=30 * interval)
                if last_date < today:
                    with sqlite3.connect('users.db') as conn:
                        conn.execute('INSERT INTO expenses (username, category, amount, date, is_recurring, recurrence_type, recurrence_interval) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                                    (username, exp[0], exp[1], last_date.strftime('%Y-%m-%d'), 0, None, None))
                        conn.commit()

    for inc in income:
        if inc[3]:  # is_recurring
            last_date = datetime.strptime(inc[2], '%Y-%m-%d')
            rec_type, interval = inc[4], inc[5]
            while last_date < today:
                if rec_type == 'daily':
                    last_date += timedelta(days=interval)
                elif rec_type == 'weekly':
                    last_date += timedelta(weeks=interval)
                elif rec_type == 'monthly':
                    last_date += timedelta(days=30 * interval)
                if last_date < today:
                    with sqlite3.connect('users.db') as conn:
                        conn.execute('INSERT INTO income (username, source, amount, date, is_recurring, recurrence_type, recurrence_interval) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                                    (username, inc[0], inc[1], last_date.strftime('%Y-%m-%d'), 0, None, None))
                        conn.commit()

    # Refresh data after recurring transactions
    with sqlite3.connect('users.db') as conn:
        expenses = conn.execute('SELECT category, amount, date FROM expenses WHERE username = ?', (username,)).fetchall()
        income = conn.execute('SELECT source, amount, date FROM income WHERE username = ?', (username,)).fetchall()

    total_income = sum(float(inc[1]) for inc in income)
    total_expenditure = sum(float(exp[1]) for exp in expenses)
    total_balance = total_income - total_expenditure

    # Budget alerts
    budget_alerts = []
    budget_dict = {b[0]: b[1] for b in budgets}
    for category in budget_dict:
        spent = sum(float(e[1]) for e in expenses if e[0] == category)
        if spent > budget_dict[category]:
            budget_alerts.append(f"Overspent on {category}: ${spent:.2f} exceeds limit ${budget_dict[category]:.2f}")

    # Chart data
    chart_data = {'labels': [], 'income': [], 'expenditure': [], 'saving': []}
    if period == 'M':
        months = ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb']
        monthly_data = defaultdict(lambda: {'income': 0, 'expenditure': 0, 'saving': 0})
        for inc in income:
            date = datetime.strptime(inc[2], '%Y-%m-%d')
            month_key = date.strftime('%b')
            if month_key in months:
                monthly_data[month_key]['income'] += float(inc[1])
        for exp in expenses:
            date = datetime.strptime(exp[2], '%Y-%m-%d')
            month_key = date.strftime('%b')
            if month_key in months:
                monthly_data[month_key]['expenditure'] += float(exp[1])
                monthly_data[month_key]['saving'] = monthly_data[month_key]['income'] - monthly_data[month_key]['expenditure']
        chart_data = {
            'labels': months,
            'income': [monthly_data[m]['income'] for m in months],
            'expenditure': [monthly_data[m]['expenditure'] for m in months],
            'saving': [monthly_data[m]['saving'] for m in months]
        }
    # Add other periods (D, W, Y) similarly if needed

    # Budget data
    categories_list = [c[0] for c in categories]
    budget_data = {}
    for cat in categories_list:
        spent = sum(float(e[1]) for e in expenses if e[0] == cat)
        budget_limit = budget_dict.get(cat, 0)
        left = budget_limit - spent if budget_limit else 0
        progress = min(100, (spent / budget_limit) * 100) if budget_limit else 0
        budget_data[cat] = {'spent': spent, 'left': left, 'progress': progress, 'budget_limit': budget_limit}

    return render_template(
        'dashboard.html',
        period=period,
        total_income=total_income,
        total_expenditure=total_expenditure,
        total_balance=total_balance,
        expenses=[{'category': e[0], 'amount': e[1], 'date': e[2]} for e in expenses][::-1],
        income=[{'source': i[0], 'amount': i[1], 'date': i[2]} for i in income][::-1],
        categories=categories_list,
        budget_data=budget_data,
        chart_data=json.dumps(chart_data),
        budget_alerts=budget_alerts,
        goals=goals
    )

@app.route('/add_income', methods=['POST'])
def add_income():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    source = request.form['source']
    amount = float(request.form['amount'])
    date = request.form['date']
    is_recurring = 'is_recurring' in request.form
    recurrence_type = request.form.get('recurrence_type', None)
    recurrence_interval = int(request.form.get('recurrence_interval', 1)) if recurrence_type else None
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT INTO income (username, source, amount, date, is_recurring, recurrence_type, recurrence_interval) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                    (session['username'], source, amount, date, is_recurring, recurrence_type, recurrence_interval))
        conn.commit()
    flash('Income added successfully!', 'success')
    return redirect(url_for('dashboard', period=request.form.get('period', 'M')))

@app.route('/add_expense', methods=['POST'])
def add_expense():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    category = request.form['category']
    amount = float(request.form['amount'])
    date = request.form['date']
    is_recurring = 'is_recurring' in request.form
    recurrence_type = request.form.get('recurrence_type', None)
    recurrence_interval = int(request.form.get('recurrence_interval', 1)) if recurrence_type else None
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT INTO expenses (username, category, amount, date, is_recurring, recurrence_type, recurrence_interval) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                    (session['username'], category, amount, date, is_recurring, recurrence_type, recurrence_interval))
        conn.commit()
    flash('Expense added successfully!', 'success')
    return redirect(url_for('dashboard', period=request.form.get('period', 'M')))

@app.route('/add_category', methods=['POST'])
def add_category():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    category = request.form['category']
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT INTO categories (username, category) VALUES (?, ?)', (session['username'], category))
        conn.commit()
    flash('Category added successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/set_budget', methods=['POST'])
def set_budget():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    category = request.form['category']
    budget_limit = float(request.form['budget_limit'])
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT OR REPLACE INTO budgets (username, category, budget_limit) VALUES (?, ?, ?)', (session['username'], category, budget_limit))
        conn.commit()
    flash('Budget set successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/add_goal', methods=['POST'])
def add_goal():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    name = request.form['name']
    target_amount = float(request.form['target_amount'])
    due_date = request.form['due_date']
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT INTO goals (username, name, target_amount, current_amount, due_date) VALUES (?, ?, ?, ?, ?)', 
                    (session['username'], name, target_amount, 0, due_date))
        conn.commit()
    flash('Goal added successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/export_csv')
def export_csv():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    username = session['username']
    with sqlite3.connect('users.db') as conn:
        expenses = conn.execute('SELECT category, amount, date FROM expenses WHERE username = ?', (username,)).fetchall()
        income = conn.execute('SELECT source, amount, date FROM income WHERE username = ?', (username,)).fetchall()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Type', 'Category/Source', 'Amount', 'Date'])
    for exp in expenses:
        cw.writerow(['Expense', exp[0], exp[1], exp[2]])
    for inc in income:
        cw.writerow(['Income', inc[0], inc[1], inc[2]])
    
    output = si.getvalue()
    si.close()
    return send_file(
        BytesIO(output.encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='transactions.csv'
    )

@app.route('/export_pdf')
def export_pdf():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    username = session['username']
    with sqlite3.connect('users.db') as conn:
        expenses = conn.execute('SELECT category, amount, date FROM expenses WHERE username = ?', (username,)).fetchall()
        income = conn.execute('SELECT source, amount, date FROM income WHERE username = ?', (username,)).fetchall()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph("SpendWise Transaction Report", styles['Heading1']))
    data = [['Type', 'Category/Source', 'Amount', 'Date']]
    for exp in expenses:
        data.append(['Expense', exp[0], f"${exp[1]:.2f}", exp[2]])
    for inc in income:
        data.append(['Income', inc[0], f"${inc[1]:.2f}", inc[2]])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='transactions.pdf'
    )

if __name__ == '__main__':
    app.run(debug=True)
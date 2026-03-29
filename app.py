from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
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
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    with sqlite3.connect('users.db') as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, email TEXT, full_name TEXT, bio TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, amount REAL, date TEXT, is_recurring INTEGER, recurrence_type TEXT, recurrence_interval INTEGER, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS income (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, source TEXT, amount REAL, date TEXT, is_recurring INTEGER, recurrence_type TEXT, recurrence_interval INTEGER, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, FOREIGN KEY(username) REFERENCES users(username))')
        conn.execute('CREATE TABLE IF NOT EXISTS budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, category TEXT, budget_limit REAL, month TEXT, FOREIGN KEY(username) REFERENCES users(username))')
        try:
            conn.execute('ALTER TABLE budgets ADD COLUMN month TEXT')
        except:
            pass
        conn.execute('CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, name TEXT, target_amount REAL, current_amount REAL, due_date TEXT, FOREIGN KEY(username) REFERENCES users(username))')
        # Add new columns if they don't exist (for existing DBs)
        try:
            conn.execute('ALTER TABLE users ADD COLUMN full_name TEXT')
        except:
            pass
        try:
            conn.execute('ALTER TABLE users ADD COLUMN bio TEXT')
        except:
            pass
        try:
            conn.execute('ALTER TABLE users ADD COLUMN profile_pic TEXT')
        except:
            pass

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
        budgets = conn.execute('SELECT category, budget_limit, month FROM budgets WHERE username = ? AND month = ?', (username, datetime.now().strftime('%Y-%m'))).fetchall()
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
        expenses = conn.execute('SELECT id, category, amount, date FROM expenses WHERE username = ?', (username,)).fetchall()
        income = conn.execute('SELECT id, source, amount, date FROM income WHERE username = ?', (username,)).fetchall()

    total_income = sum(float(inc[2]) for inc in income)
    total_expenditure = sum(float(exp[2]) for exp in expenses)
    total_balance = total_income - total_expenditure

    # Current month filter
    current_month = today.strftime('%Y-%m')
    monthly_expenses = [e for e in expenses if e[3].startswith(current_month)]

    # budget_dict keyed by (category, month)
    budget_dict = {(b[0], b[2]): b[1] for b in budgets}
    total_budget = sum(b[1] for b in budgets if b[2] == current_month)

    # Budget alerts — same month चे ALL expenses vs limit
    budget_alerts = []
    for b in budgets:
        cat, limit, month = b[0], b[1], b[2]
        spent = sum(float(e[2]) for e in expenses if e[3].startswith(month))
        if spent > limit:
            budget_alerts.append(f"⚠️ {cat} ({month}): Spent ${spent:.2f} — Over budget by ${spent - limit:.2f}!")

    # Chart data
    chart_data = {'labels': [], 'income': [], 'expenditure': [], 'saving': []}
    if period == 'M':
        # Last 6 months dynamically
        months_list = []
        for i in range(5, -1, -1):
            month_num = today.month - i
            year = today.year
            while month_num <= 0:
                month_num += 12
                year -= 1
            months_list.append(f"{year}-{month_num:02d}")
        monthly_data = defaultdict(lambda: {'income': 0, 'expenditure': 0, 'saving': 0})
        for inc in income:
            key = inc[3][:7]
            if key in months_list:
                monthly_data[key]['income'] += float(inc[2])
        for exp in expenses:
            key = exp[3][:7]
            if key in months_list:
                monthly_data[key]['expenditure'] += float(exp[2])
        for key in months_list:
            monthly_data[key]['saving'] = monthly_data[key]['income'] - monthly_data[key]['expenditure']
        chart_data = {
            'labels': [datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in months_list],
            'income': [monthly_data[m]['income'] for m in months_list],
            'expenditure': [monthly_data[m]['expenditure'] for m in months_list],
            'saving': [monthly_data[m]['saving'] for m in months_list]
        }

    # Budget data — same month चे ALL expenses count करायचे (category match नाही)
    categories_list = [c[0] for c in categories]
    budget_data = {}
    for b in budgets:
        cat, limit, month = b[0], b[1], b[2]
        # All expenses of that month for this user
        cat_expenses = [e for e in expenses if e[3].startswith(month)]
        spent = sum(float(e[2]) for e in cat_expenses)
        left = limit - spent
        progress = min(100, (spent / limit) * 100) if limit else 0
        key = f"{cat}||{month}"
        budget_data[key] = {
            'category': cat,
            'month': month,
            'spent': spent,
            'left': left,
            'progress': progress,
            'budget_limit': limit,
            'expenses': [{'amount': e[2], 'date': e[3], 'category': e[1]} for e in cat_expenses]
        }

    # Merge budget categories into categories_list for expense dropdown
    budget_cats = [b[0] for b in budgets]
    for bc in budget_cats:
        if bc not in categories_list:
            categories_list.append(bc)

    return render_template(
        'dashboard.html',
        period=period,
        total_income=total_income,
        total_expenditure=total_expenditure,
        total_balance=total_balance,
        total_budget=total_budget,
        expenses=[{'id': e[0], 'category': e[1], 'amount': e[2], 'date': e[3]} for e in expenses][::-1],
        income=[{'id': i[0], 'source': i[1], 'amount': i[2], 'date': i[3]} for i in income][::-1],
        categories=categories_list,
        budget_data=budget_data,
        chart_data=json.dumps(chart_data),
        budget_alerts=budget_alerts,
        goals=goals,
        now=today
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
    category = request.form['category'].strip()
    budget_limit = float(request.form['budget_limit'])
    # Combine month + year on server side — no JS dependency
    m = request.form.get('budget_month_m', '').zfill(2)
    y = request.form.get('budget_month_y', '')
    month = f"{y}-{m}" if y and m else datetime.now().strftime('%Y-%m')
    with sqlite3.connect('users.db') as conn:
        existing = conn.execute(
            'SELECT id FROM budgets WHERE username=? AND category=? AND month=?',
            (session['username'], category, month)
        ).fetchone()
        if existing:
            conn.execute('UPDATE budgets SET budget_limit=? WHERE id=?', (budget_limit, existing[0]))
        else:
            conn.execute('INSERT INTO budgets (username, category, budget_limit, month) VALUES (?, ?, ?, ?)',
                         (session['username'], category, budget_limit, month))
        conn.commit()
    flash(f'Budget set for {category} — {month}!', 'success')
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

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'username' not in session:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    username = session['username']
    if request.method == 'POST':
        full_name = request.form.get('full_name', '')
        email = request.form.get('email', '')
        bio = request.form.get('bio', '')
        file = request.files.get('profile_pic')
        pic_filename = None
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{username}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pic_filename = filename
        with sqlite3.connect('users.db') as conn:
            if pic_filename:
                conn.execute('UPDATE users SET full_name=?, email=?, bio=?, profile_pic=? WHERE username=?',
                             (full_name, email, bio, pic_filename, username))
            else:
                conn.execute('UPDATE users SET full_name=?, email=?, bio=? WHERE username=?',
                             (full_name, email, bio, username))
            conn.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    with sqlite3.connect('users.db') as conn:
        user = conn.execute('SELECT username, email, full_name, bio, profile_pic FROM users WHERE username=?', (username,)).fetchone()
        total_income = conn.execute('SELECT COALESCE(SUM(amount),0) FROM income WHERE username=?', (username,)).fetchone()[0]
        total_expenses = conn.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE username=?', (username,)).fetchone()[0]
        total_goals = conn.execute('SELECT COUNT(*) FROM goals WHERE username=?', (username,)).fetchone()[0]
    return render_template('profile.html', user=user, total_income=total_income, total_expenses=total_expenses, total_goals=total_goals)

@app.route('/delete_expense/<int:expense_id>')
def delete_expense(expense_id):
    if 'username' not in session:
        return redirect(url_for('signin'))
    with sqlite3.connect('users.db') as conn:
        conn.execute('DELETE FROM expenses WHERE id=? AND username=?', (expense_id, session['username']))
        conn.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/delete_income/<int:income_id>')
def delete_income(income_id):
    if 'username' not in session:
        return redirect(url_for('signin'))
    with sqlite3.connect('users.db') as conn:
        conn.execute('DELETE FROM income WHERE id=? AND username=?', (income_id, session['username']))
        conn.commit()
    flash('Income deleted.', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
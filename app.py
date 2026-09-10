import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER_VIDEOS'] = 'uploads/videos'
app.config['UPLOAD_FOLDER_PDFS'] = 'uploads/pdfs'
app.config['UPLOAD_FOLDER_THUMBNAILS'] = 'uploads/thumbnails'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max

# Email configuration (configure with your SMTP settings)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', '')

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
ALLOWED_PDF_EXTENSIONS = {'pdf'}

def allowed_video_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

def allowed_pdf_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PDF_EXTENSIONS

# ==================== MODELS ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=True)  # Nullable for admin-created accounts
    phone = db.Column(db.String(20), unique=True, nullable=True)  # Nullable for admin-created accounts
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # 'admin' or 'student'
    is_approved = db.Column(db.Boolean, default=False)  # For student approval
    is_pending = db.Column(db.Boolean, default=True)  # True if awaiting approval
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    quiz_attempts = db.relationship('QuizAttempt', backref='user', lazy=True)
    exam_attempts = db.relationship('ExamAttempt', backref='user', lazy=True)
    questions = db.relationship('Question', backref='author', lazy=True)
    complaints = db.relationship('Complaint', backref='user', lazy=True)

class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    video_filename = db.Column(db.String(300), nullable=True)
    pdf_filename = db.Column(db.String(300), nullable=True)
    order_index = db.Column(db.Integer, nullable=False, default=0)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    quiz = db.relationship('Quiz', backref='lesson', uselist=False, cascade='all, delete-orphan')
    course = db.relationship('Course', backref='lessons')

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    thumbnail_filename = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    exams = db.relationship('Exam', backref='course', lazy=True)

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False, unique=True)
    passing_score = db.Column(db.Integer, default=70)  # Percentage required to pass
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade='all, delete-orphan')
    attempts = db.relationship('QuizAttempt', backref='quiz', lazy=True, cascade='all, delete-orphan')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), default='multiple_choice')  # multiple_choice, true_false
    option_a = db.Column(db.String(300), nullable=True)
    option_b = db.Column(db.String(300), nullable=True)
    option_c = db.Column(db.String(300), nullable=True)
    option_d = db.Column(db.String(300), nullable=True)
    correct_answer = db.Column(db.String(10), nullable=False)  # 'A', 'B', 'C', 'D', 'True', 'False'
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)  # Percentage
    passed = db.Column(db.Boolean, default=False)
    answers = db.Column(db.Text, nullable=True)  # JSON string of answers
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)
    passing_score = db.Column(db.Integer, default=50)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    questions = db.relationship('ExamQuestion', backref='exam', lazy=True, cascade='all, delete-orphan')
    attempts = db.relationship('ExamAttempt', backref='exam', lazy=True, cascade='all, delete-orphan')

class ExamQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), default='multiple_choice')
    option_a = db.Column(db.String(300), nullable=True)
    option_b = db.Column(db.String(300), nullable=True)
    option_c = db.Column(db.String(300), nullable=True)
    option_d = db.Column(db.String(300), nullable=True)
    correct_answer = db.Column(db.String(10), nullable=False)
    points = db.Column(db.Integer, default=1)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)

class ExamAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_points = db.Column(db.Integer, nullable=False)
    passed = db.Column(db.Boolean, default=False)
    answers = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)

class LiveStream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    stream_url = db.Column(db.String(500), nullable=True)  # For embedding stream
    is_active = db.Column(db.Boolean, default=False)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class QuestionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='questions')

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, in_progress, resolved
    admin_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LessonProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    watched = db.Column(db.Boolean, default=False)
    quiz_passed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    lesson = db.relationship('Lesson', backref='progress_records')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== ROUTES ====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            if not current_user.is_approved:
                return redirect(url_for('pending_approval'))
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        name = request.form.get('name')
        
        # Validate Egyptian phone number
        if not phone or not phone.startswith('01') or len(phone) != 11 or not phone.isdigit():
            flash('يرجى إدخال رقم هاتف مصري صحيح (يبدأ بـ 01 ويتكون من 11 رقم)', 'danger')
            return render_template('register.html')
        
        # Validate email
        if not email or '@' not in email:
            flash('يرجى إدخال بريد إلكتروني صحيح', 'danger')
            return render_template('register.html')
        
        # Check if email or phone already exists
        if User.query.filter_by(email=email).first():
            flash('البريد الإلكتروني مسجل بالفعل', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(phone=phone).first():
            flash('رقم الهاتف مسجل بالفعل', 'danger')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('كلمات المرور غير متطابقة', 'danger')
            return render_template('register.html')
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        new_user = User(
            email=email,
            phone=phone,
            password=hashed_password,
            name=name,
            role='student',
            is_approved=False,
            is_pending=True
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('تم تسجيل حسابك بنجاح. يرجى انتظار موافقة المدير.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_phone = request.form.get('email_or_phone')
        password = request.form.get('password')
        
        user = User.query.filter(
            (User.email == email_or_phone) | (User.phone == email_or_phone)
        ).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            if user.role == 'admin':
                login_user(user)
                return redirect(url_for('admin_dashboard'))
            
            if not user.is_approved:
                if user.is_pending:
                    flash('حسابك قيد المراجعة من قبل الإدارة. يرجى الانتظار.', 'warning')
                else:
                    flash('تم رفض حسابك. يرجى التواصل مع الإدارة.', 'danger')
                return render_template('login.html')
            
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('student_dashboard'))
        else:
            flash('البريد الإلكتروني/رقم الهاتف أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template('login.html')

@app.route('/pending_approval')
@login_required
def pending_approval():
    if current_user.role == 'admin' or current_user.is_approved:
        return redirect(url_for('index'))
    return render_template('pending_approval.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            # In production, store token in database with expiry
            # For now, we'll send a simple email
            try:
                msg = Message(
                    'إعادة تعيين كلمة المرور',
                    recipients=[user.email]
                )
                reset_url = url_for('reset_password', token=token, _external=True)
                msg.body = f'''مرحباً {user.name},
                
لإعادة تعيين كلمة المرور، اضغط على الرابط التالي:
{reset_url}

إذا لم تطلب إعادة تعيين كلمة المرور، تجاهل هذا البريد.
'''
                mail.send(msg)
                flash('تم إرسال رابط إعادة تعيين كلمة المرور إلى بريدك الإلكتروني', 'success')
            except Exception as e:
                flash(f'حدث خطأ أثناء إرسال البريد: {str(e)}. يرجى التواصل مع الإدارة.', 'danger')
        else:
            flash('لا يوجد حساب بهذا البريد الإلكتروني', 'danger')
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # In production, validate token from database
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        email = request.form.get('email')
        
        if password != confirm_password:
            flash('كلمات المرور غير متطابقة', 'danger')
            return render_template('reset_password.html', token=token)
        
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.commit()
            flash('تم تغيير كلمة المرور بنجاح', 'success')
            return redirect(url_for('login'))
        else:
            flash('حدث خطأ. يرجى المحاولة مرة أخرى.', 'danger')
    
    return render_template('reset_password.html', token=token)

# ==================== ADMIN ROUTES ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('غير مصرح لك بالوصول إلى هذه الصفحة', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    students = User.query.filter_by(role='student').all()
    pending_students = User.query.filter_by(role='student', is_pending=True, is_approved=False).all()
    courses = Course.query.all()
    lessons_count = Lesson.query.count()
    quizzes_count = Quiz.query.count()
    exams_count = Exam.query.count()
    return render_template('admin/dashboard.html', 
                         students=students, 
                         pending_students=pending_students,
                         courses=courses,
                         lessons_count=lessons_count,
                         quizzes_count=quizzes_count,
                         exams_count=exams_count)

@app.route('/admin/students')
@admin_required
def admin_students():
    students = User.query.filter_by(role='student').all()
    return render_template('admin/students.html', students=students)

@app.route('/admin/approve_student/<int:student_id>')
@admin_required
def approve_student(student_id):
    student = User.query.get_or_404(student_id)
    if student.role == 'student':
        student.is_approved = True
        student.is_pending = False
        db.session.commit()
        flash(f'تم قبول الطالب {student.name}', 'success')
    return redirect(url_for('admin_students'))

@app.route('/admin/reject_student/<int:student_id>')
@admin_required
def reject_student(student_id):
    student = User.query.get_or_404(student_id)
    if student.role == 'student':
        student.is_approved = False
        student.is_pending = False
        db.session.commit()
        flash(f'تم رفض الطالب {student.name}', 'info')
    return redirect(url_for('admin_students'))

@app.route('/admin/create_student', methods=['GET', 'POST'])
@admin_required
def admin_create_student():
    if request.method == 'POST':
        name = request.form.get('name')
        generate_credentials = request.form.get('generate_credentials') == 'on'
        
        if generate_credentials:
            # Generate random credentials
            phone = f"01{secrets.randbelow(10**9):09d}"
            password = secrets.token_urlsafe(8)
            email = None
        else:
            email = request.form.get('email')
            phone = request.form.get('phone')
            password = request.form.get('password')
            
            if email and User.query.filter_by(email=email).first():
                flash('البريد الإلكتروني مسجل بالفعل', 'danger')
                return render_template('admin/create_student.html')
            
            if phone and User.query.filter_by(phone=phone).first():
                flash('رقم الهاتف مسجل بالفعل', 'danger')
                return render_template('admin/create_student.html')
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        new_user = User(
            email=email,
            phone=phone,
            password=hashed_password,
            name=name,
            role='student',
            is_approved=True,
            is_pending=False
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        if generate_credentials:
            flash(f'تم إنشاء الحساب بنجاح. رقم الهاتف: {phone}, كلمة المرور: {password}', 'success')
        else:
            flash('تم إنشاء الحساب بنجاح', 'success')
        
        return redirect(url_for('admin_students'))
    
    return render_template('admin/create_student.html')

@app.route('/admin/courses')
@admin_required
def admin_courses():
    courses = Course.query.all()
    return render_template('admin/courses.html', courses=courses)

@app.route('/admin/course/add', methods=['GET', 'POST'])
@admin_required
def admin_add_course():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        
        new_course = Course(title=title, description=description)
        db.session.add(new_course)
        db.session.commit()
        
        flash('تم إضافة المقرر بنجاح', 'success')
        return redirect(url_for('admin_courses'))
    
    return render_template('admin/course_form.html', course=None)

@app.route('/admin/course/edit/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        course.title = request.form.get('title')
        course.description = request.form.get('description')
        db.session.commit()
        
        flash('تم تحديث المقرر بنجاح', 'success')
        return redirect(url_for('admin_courses'))
    
    return render_template('admin/course_form.html', course=course)

@app.route('/admin/lessons/<int:course_id>')
@admin_required
def admin_lessons(course_id):
    course = Course.query.get_or_404(course_id)
    lessons = Lesson.query.filter_by(course_id=course_id).order_by(Lesson.order_index).all()
    return render_template('admin/lessons.html', course=course, lessons=lessons)

@app.route('/admin/lesson/add/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def admin_add_lesson(course_id):
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        order_index = request.form.get('order_index', 0)
        
        video = request.files.get('video')
        pdf = request.files.get('pdf')
        
        video_filename = None
        pdf_filename = None
        
        if video and allowed_video_file(video.filename):
            video_filename = secure_filename(f"{secrets.token_hex(8)}_{video.filename}")
            video.save(os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], video_filename))
        
        if pdf and allowed_pdf_file(pdf.filename):
            pdf_filename = secure_filename(f"{secrets.token_hex(8)}_{pdf.filename}")
            pdf.save(os.path.join(app.config['UPLOAD_FOLDER_PDFS'], pdf_filename))
        
        new_lesson = Lesson(
            title=title,
            description=description,
            video_filename=video_filename,
            pdf_filename=pdf_filename,
            order_index=int(order_index),
            course_id=course_id
        )
        
        db.session.add(new_lesson)
        db.session.commit()
        
        flash('تم إضافة الدرس بنجاح', 'success')
        return redirect(url_for('admin_lessons', course_id=course_id))
    
    return render_template('admin/lesson_form.html', course=course, lesson=None)

@app.route('/admin/lesson/edit/<int:lesson_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_lesson(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    course = Course.query.get_or_404(lesson.course_id)
    
    if request.method == 'POST':
        lesson.title = request.form.get('title')
        lesson.description = request.form.get('description')
        lesson.order_index = int(request.form.get('order_index', 0))
        
        video = request.files.get('video')
        pdf = request.files.get('pdf')
        
        if video and allowed_video_file(video.filename):
            # Delete old video
            if lesson.video_filename:
                old_video_path = os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], lesson.video_filename)
                if os.path.exists(old_video_path):
                    os.remove(old_video_path)
            
            lesson.video_filename = secure_filename(f"{secrets.token_hex(8)}_{video.filename}")
            video.save(os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], lesson.video_filename))
        
        if pdf and allowed_pdf_file(pdf.filename):
            # Delete old PDF
            if lesson.pdf_filename:
                old_pdf_path = os.path.join(app.config['UPLOAD_FOLDER_PDFS'], lesson.pdf_filename)
                if os.path.exists(old_pdf_path):
                    os.remove(old_pdf_path)
            
            lesson.pdf_filename = secure_filename(f"{secrets.token_hex(8)}_{pdf.filename}")
            pdf.save(os.path.join(app.config['UPLOAD_FOLDER_PDFS'], pdf_filename))
        
        db.session.commit()
        
        flash('تم تحديث الدرس بنجاح', 'success')
        return redirect(url_for('admin_lessons', course_id=course_id))
    
    return render_template('admin/lesson_form.html', course=course, lesson=lesson)

@app.route('/admin/quiz/add/<int:lesson_id>', methods=['GET', 'POST'])
@admin_required
def admin_add_quiz(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    
    if request.method == 'POST':
        title = request.form.get('title')
        passing_score = int(request.form.get('passing_score', 70))
        
        quiz = Quiz(title=title, lesson_id=lesson_id, passing_score=passing_score)
        db.session.add(quiz)
        db.session.commit()
        
        # Add questions
        question_texts = request.form.getlist('question_text[]')
        question_types = request.form.getlist('question_type[]')
        option_as = request.form.getlist('option_a[]')
        option_bs = request.form.getlist('option_b[]')
        option_cs = request.form.getlist('option_c[]')
        option_ds = request.form.getlist('option_d[]')
        correct_answers = request.form.getlist('correct_answer[]')
        
        for i, text in enumerate(question_texts):
            if text:
                question = Question(
                    text=text,
                    question_type=question_types[i],
                    option_a=option_as[i],
                    option_b=option_bs[i],
                    option_c=option_cs[i],
                    option_d=option_ds[i],
                    correct_answer=correct_answers[i],
                    quiz_id=quiz.id,
                    author_id=current_user.id
                )
                db.session.add(question)
        
        db.session.commit()
        flash('تم إضافة الاختبار بنجاح', 'success')
        return redirect(url_for('admin_lessons', course_id=lesson.course_id))
    
    return render_template('admin/quiz_form.html', lesson=lesson, quiz=None)

@app.route('/admin/exams')
@admin_required
def admin_exams():
    exams = Exam.query.all()
    return render_template('admin/exams.html', exams=exams)

@app.route('/admin/exam/add', methods=['GET', 'POST'])
@admin_required
def admin_add_exam():
    courses = Course.query.all()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = int(request.form.get('course_id'))
        duration_minutes = int(request.form.get('duration_minutes', 60))
        passing_score = int(request.form.get('passing_score', 50))
        
        new_exam = Exam(
            title=title,
            description=description,
            course_id=course_id,
            duration_minutes=duration_minutes,
            passing_score=passing_score
        )
        db.session.add(new_exam)
        db.session.commit()
        
        # Add questions
        question_texts = request.form.getlist('question_text[]')
        question_types = request.form.getlist('question_type[]')
        option_as = request.form.getlist('option_a[]')
        option_bs = request.form.getlist('option_b[]')
        option_cs = request.form.getlist('option_c[]')
        option_ds = request.form.getlist('option_d[]')
        correct_answers = request.form.getlist('correct_answer[]')
        points_list = request.form.getlist('points[]')
        
        for i, text in enumerate(question_texts):
            if text:
                question = ExamQuestion(
                    text=text,
                    question_type=question_types[i],
                    option_a=option_as[i],
                    option_b=option_bs[i],
                    option_c=option_cs[i],
                    option_d=option_ds[i],
                    correct_answer=correct_answers[i],
                    points=int(points_list[i]) if points_list[i] else 1,
                    exam_id=new_exam.id
                )
                db.session.add(question)
        
        db.session.commit()
        flash('تم إضافة الامتحان بنجاح', 'success')
        return redirect(url_for('admin_exams'))
    
    return render_template('admin/exam_form.html', exam=None, courses=courses)

@app.route('/admin/livestreams')
@admin_required
def admin_livestreams():
    streams = LiveStream.query.order_by(LiveStream.created_at.desc()).all()
    return render_template('admin/livestreams.html', streams=streams)

@app.route('/admin/livestream/add', methods=['GET', 'POST'])
@admin_required
def admin_add_livestream():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        stream_url = request.form.get('stream_url')  # YouTube Live, OBS, etc.
        is_active = request.form.get('is_active') == 'on'
        
        new_stream = LiveStream(
            title=title,
            description=description,
            stream_url=stream_url,
            is_active=is_active,
            created_by=current_user.id
        )
        db.session.add(new_stream)
        db.session.commit()
        
        flash('تم إضافة البث المباشر بنجاح', 'success')
        return redirect(url_for('admin_livestreams'))
    
    return render_template('admin/livestream_form.html', stream=None)

@app.route('/admin/livestream/edit/<int:stream_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_livestream(stream_id):
    stream = LiveStream.query.get_or_404(stream_id)
    
    if request.method == 'POST':
        stream.title = request.form.get('title')
        stream.description = request.form.get('description')
        stream.stream_url = request.form.get('stream_url')
        stream.is_active = request.form.get('is_active') == 'on'
        db.session.commit()
        
        flash('تم تحديث البث المباشر بنجاح', 'success')
        return redirect(url_for('admin_livestreams'))
    
    return render_template('admin/livestream_form.html', stream=stream)

@app.route('/admin/questions')
@admin_required
def admin_questions():
    questions = QuestionItem.query.order_by(QuestionItem.created_at.desc()).all()
    return render_template('admin/questions.html', questions=questions)

@app.route('/admin/question/respond/<int:question_id>', methods=['POST'])
@admin_required
def admin_respond_question(question_id):
    question = QuestionItem.query.get_or_404(question_id)
    response = request.form.get('response')
    is_resolved = request.form.get('is_resolved') == 'on'
    
    question.response = response
    question.is_resolved = is_resolved
    db.session.commit()
    
    flash('تم الرد على الاستفسار', 'success')
    return redirect(url_for('admin_questions'))

@app.route('/admin/complaints')
@admin_required
def admin_complaints():
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return render_template('admin/complaints.html', complaints=complaints)

@app.route('/admin/complaint/respond/<int:complaint_id>', methods=['POST'])
@admin_required
def admin_respond_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    admin_response = request.form.get('admin_response')
    status = request.form.get('status')
    
    complaint.admin_response = admin_response
    complaint.status = status
    db.session.commit()
    
    flash('تم الرد على الشكوى', 'success')
    return redirect(url_for('admin_complaints'))

# ==================== STUDENT ROUTES ====================

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student' or not current_user.is_approved:
        return redirect(url_for('login'))
    
    courses = Course.query.all()
    # Get user's progress
    user_lessons = LessonProgress.query.filter_by(user_id=current_user.id).all()
    completed_lesson_ids = [lp.lesson_id for lp in user_lessons if lp.watched and lp.quiz_passed]
    
    return render_template('student/dashboard.html', courses=courses, completed_lessons=completed_lesson_ids)

@app.route('/student/course/<int:course_id>')
@login_required
def student_course(course_id):
    if current_user.role != 'student' or not current_user.is_approved:
        return redirect(url_for('login'))
    
    course = Course.query.get_or_404(course_id)
    lessons = Lesson.query.filter_by(course_id=course_id).order_by(Lesson.order_index).all()
    
    # Get user's progress for each lesson
    progress = {}
    for lesson in lessons:
        lp = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson.id).first()
        if lp:
            progress[lesson.id] = {'watched': lp.watched, 'quiz_passed': lp.quiz_passed}
        else:
            progress[lesson.id] = {'watched': False, 'quiz_passed': False}
    
    return render_template('student/course.html', course=course, lessons=lessons, progress=progress)

@app.route('/student/lesson/<int:lesson_id>')
@login_required
def student_lesson(lesson_id):
    if current_user.role != 'student' or not current_user.is_approved:
        return redirect(url_for('login'))
    
    lesson = Lesson.query.get_or_404(lesson_id)
    
    # Check if previous lessons are completed
    previous_lessons = Lesson.query.filter(
        Lesson.course_id == lesson.course_id,
        Lesson.order_index < lesson.order_index
    ).order_by(Lesson.order_index).all()
    
    can_access = True
    blocked_lesson = None
    
    for prev_lesson in previous_lessons:
        lp = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=prev_lesson.id).first()
        if not lp or not lp.watched or not lp.quiz_passed:
            can_access = False
            blocked_lesson = prev_lesson
            break
    
    # Get or create progress record
    progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).first()
    if not progress:
        progress = LessonProgress(user_id=current_user.id, lesson_id=lesson_id, watched=False, quiz_passed=False)
        db.session.add(progress)
        db.session.commit()
    
    quiz = Quiz.query.filter_by(lesson_id=lesson_id).first()
    quiz_attempt = None
    if quiz:
        quiz_attempt = QuizAttempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).first()
    
    return render_template('student/lesson.html', 
                         lesson=lesson, 
                         progress=progress, 
                         quiz=quiz, 
                         quiz_attempt=quiz_attempt,
                         can_access=can_access,
                         blocked_lesson=blocked_lesson)

@app.route('/student/mark_watched/<int:lesson_id>', methods=['POST'])
@login_required
def student_mark_watched(lesson_id):
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).first()
    if progress:
        progress.watched = True
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'error': 'Progress not found'}), 404

@app.route('/student/quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def student_quiz(quiz_id):
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    quiz = Quiz.query.get_or_404(quiz_id)
    lesson = Lesson.query.get_or_404(quiz.lesson_id)
    
    if request.method == 'POST':
        answers = {}
        for question in quiz.questions:
            answer = request.form.get(f'question_{question.id}')
            answers[str(question.id)] = answer
        
        # Calculate score
        correct_count = 0
        for question in quiz.questions:
            if answers.get(str(question.id)) == question.correct_answer:
                correct_count += 1
        
        score = int((correct_count / len(quiz.questions)) * 100) if quiz.questions else 0
        passed = score >= quiz.passing_score
        
        # Save attempt
        attempt = QuizAttempt(
            user_id=current_user.id,
            quiz_id=quiz_id,
            score=score,
            passed=passed,
            answers=str(answers)
        )
        db.session.add(attempt)
        
        # Update progress
        progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson.id).first()
        if progress and passed:
            progress.quiz_passed = True
            if progress.watched:
                progress.completed_at = datetime.utcnow()
        
        db.session.commit()
        
        flash(f'نتيجتك: {score}%. {"مبروك! لقد اجتزت الاختبار." if passed else "حاول مرة أخرى."}', 'success' if passed else 'warning')
        return redirect(url_for('student_lesson', lesson_id=lesson.id))
    
    return render_template('student/quiz.html', quiz=quiz, lesson=lesson)

@app.route('/student/exams')
@login_required
def student_exams():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    exams = Exam.query.filter_by(is_active=True).all()
    return render_template('student/exams.html', exams=exams)

@app.route('/student/exam/<int:exam_id>')
@login_required
def student_exam(exam_id):
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    exam = Exam.query.get_or_404(exam_id)
    
    # Check if already attempted
    existing_attempt = ExamAttempt.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
    
    return render_template('student/exam.html', exam=exam, existing_attempt=existing_attempt)

@app.route('/student/exam/submit/<int:exam_id>', methods=['POST'])
@login_required
def student_submit_exam(exam_id):
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    exam = Exam.query.get_or_404(exam_id)
    
    answers = {}
    for question in exam.questions:
        answer = request.form.get(f'question_{question.id}')
        answers[str(question.id)] = answer
    
    # Calculate score
    total_points = sum(q.points for q in exam.questions)
    earned_points = 0
    for question in exam.questions:
        if answers.get(str(question.id)) == question.correct_answer:
            earned_points += question.points
    
    score = int((earned_points / total_points) * 100) if total_points > 0 else 0
    passed = score >= exam.passing_score
    
    attempt = ExamAttempt(
        user_id=current_user.id,
        exam_id=exam_id,
        score=score,
        total_points=earned_points,
        passed=passed,
        answers=str(answers),
        submitted_at=datetime.utcnow()
    )
    db.session.add(attempt)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'score': score,
        'total_points': earned_points,
        'max_points': total_points,
        'passed': passed
    })

@app.route('/student/livestreams')
@login_required
def student_livestreams():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    streams = LiveStream.query.filter_by(is_active=True).order_by(LiveStream.created_at.desc()).all()
    return render_template('student/livestreams.html', streams=streams)

@app.route('/student/ask_question', methods=['GET', 'POST'])
@login_required
def student_ask_question():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        question = QuestionItem(
            user_id=current_user.id,
            subject=subject,
            message=message
        )
        db.session.add(question)
        db.session.commit()
        
        flash('تم إرسال استفسارك بنجاح', 'success')
        return redirect(url_for('student_questions'))
    
    return render_template('student/ask_question.html')

@app.route('/student/questions')
@login_required
def student_questions():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    questions = QuestionItem.query.filter_by(user_id=current_user.id).order_by(QuestionItem.created_at.desc()).all()
    return render_template('student/questions.html', questions=questions)

@app.route('/student/complaint', methods=['GET', 'POST'])
@login_required
def student_complaint():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        complaint = Complaint(
            user_id=current_user.id,
            subject=subject,
            message=message
        )
        db.session.add(complaint)
        db.session.commit()
        
        flash('تم إرسال شكواك بنجاح', 'success')
        return redirect(url_for('student_complaints'))
    
    return render_template('student/complaint.html')

@app.route('/student/complaints')
@login_required
def student_complaints():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    complaints = Complaint.query.filter_by(user_id=current_user.id).order_by(Complaint.created_at.desc()).all()
    return render_template('student/complaints.html', complaints=complaints)

# ==================== FILE SERVING ====================

@app.route('/uploads/videos/<filename>')
@login_required
def serve_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER_VIDEOS'], filename)

@app.route('/uploads/pdfs/<filename>')
@login_required
def serve_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER_PDFS'], filename)

# ==================== INITIALIZATION ====================

def create_admin():
    with app.app_context():
        admin = User.query.filter_by(email='7hmed4ref@gmail.com').first()
        if not admin:
            hashed_password = bcrypt.generate_password_hash('011156').decode('utf-8')
            admin = User(
                email='7hmed4ref@gmail.com',
                password=hashed_password,
                name='المدير',
                role='admin',
                is_approved=True,
                is_pending=False
            )
            db.session.add(admin)
            db.session.commit()
            print('Admin user created successfully!')
        else:
            print('Admin user already exists.')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin()
    app.run(debug=True, host='0.0.0.0', port=5000)

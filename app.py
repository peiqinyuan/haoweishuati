import json
import re
import os
import uuid
import random
import string
from datetime import datetime, date, timedelta
from functools import wraps
from threading import Lock

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import func, or_, text

from config import Config
from models import (db, User, Question, AnswerRecord, WrongQuestion, DayStat, UploadLog,
                    SUBJECTS, Exam, ExamQuestion, ExamResult,
                    QuestionBank, DailyCheckin, UserKeyQuestion,
                    MatchRoom, MatchPlayer, MatchAnswer)
from utils.recommendation import RecommendationEngine
from utils.word_parser import WordParser

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'

recommendation = RecommendationEngine()
word_parser = WordParser(Config.UPLOAD_FOLDER)

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ===================== 页面路由 =====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/register')
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/practice')
@login_required
def practice():
    return render_template('practice.html')


@app.route('/wrong-book')
@login_required
def wrong_book():
    return render_template('wrong_book.html')


@app.route('/upload')
@login_required
def upload():
    return render_template('upload.html')


@app.route('/add-question')
@login_required
def add_question():
    return render_template('add_question.html')


@app.route('/analysis')
@login_required
def analysis():
    return render_template('analysis.html')


@app.route('/similar/<int:question_id>')
@login_required
def similar_page(question_id):
    return render_template('similar.html', question_id=question_id)


@app.route('/exams')
@login_required
def exams_page():
    return render_template('exams.html')


@app.route('/exam/<exam_code>')
@login_required
def exam_take_page(exam_code):
    return render_template('exam_take.html', exam_code=exam_code)


@app.route('/banks')
@login_required
def banks_page():
    return render_template('banks.html')


@app.route('/bank/<int:bank_id>')
@login_required
def bank_detail_page(bank_id):
    return render_template('bank_detail.html', bank_id=bank_id)


@app.route('/match')
@login_required
def match_page():
    return render_template('match.html')


@app.route('/match/<code>')
@login_required
def match_room_page(code):
    return render_template('match_room.html', code=code)


@app.route('/points')
@login_required
def points_page():
    return render_template('points.html')


# ===================== 认证API =====================

def api_response(success, message='', data=None, code=200):
    return jsonify({'success': success, 'message': message, 'data': data}), code


@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not username or not email or not password:
        return api_response(False, '所有字段都是必填的', code=400)
    if len(username) < 2 or len(username) > 20:
        return api_response(False, '用户名长度需要在2-20个字符之间', code=400)
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return api_response(False, '邮箱格式不正确', code=400)
    if len(password) < 6:
        return api_response(False, '密码长度至少需要6位', code=400)

    if User.query.filter_by(username=username).first():
        return api_response(False, '用户名已被使用', code=400)
    if User.query.filter_by(email=email).first():
        return api_response(False, '邮箱已被注册', code=400)

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return api_response(True, '注册成功', {'user': user.to_dict()}, 201)


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    identifier = (data.get('identifier') or '').strip()
    password = data.get('password') or ''
    remember = data.get('remember', False)

    if not identifier or not password:
        return api_response(False, '请输入账号和密码', code=400)

    user = User.query.filter(or_(User.username == identifier, User.email == identifier)).first()
    if not user or not user.check_password(password):
        return api_response(False, '账号或密码错误', code=400)

    user.last_active = datetime.utcnow()
    db.session.commit()

    login_user(user, remember=remember)
    return api_response(True, '登录成功', {'user': user.to_dict()})


@app.route('/api/logout', methods=['POST'])
@login_required
def api_logout():
    logout_user()
    return api_response(True, '已退出登录')


@app.route('/api/user')
@login_required
def api_user():
    return api_response(True, 'ok', {'user': current_user.to_dict()})


# ===================== 题目API =====================

@app.route('/api/subjects')
def api_subjects():
    q = Question.query.filter(Question.bank_id.is_(None)).with_entities(
        Question.subject, func.count(Question.id)).group_by(Question.subject).all()
    subject_counts = {s: c for s, c in q}
    return api_response(True, 'ok', {
        'subjects': subject_counts,
        'all_subjects': SUBJECTS
    })


@app.route('/api/questions', methods=['GET'])
@login_required
def api_get_questions():
    """获取题目列表，支持过滤和分页"""
    subject = request.args.get('subject', '')
    difficulty = request.args.get('difficulty', '')
    qtype = request.args.get('type', '')
    keyword = request.args.get('keyword', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    only_wrong = request.args.get('only_wrong', '') == 'true'
    mastered_only = request.args.get('mastered', '') == 'true'

    query = Question.query.filter(Question.bank_id.is_(None))
    if subject and subject != 'all':
        query = query.filter(Question.subject == subject)
    if difficulty and difficulty != 'all':
        query = query.filter(Question.difficulty == int(difficulty))
    if qtype and qtype != 'all':
        query = query.filter(Question.type == qtype)
    if keyword:
        query = query.filter(or_(
            Question.content.contains(keyword),
            Question.tags.contains(keyword),
            Question.topic.contains(keyword)
        ))

    if only_wrong:
        wrong_ids = [w.question_id for w in WrongQuestion.query.filter_by(
            user_id=current_user.id, is_mastered=False).all()]
        query = query.filter(Question.id.in_(wrong_ids))
    elif mastered_only:
        mastered_ids = [w.question_id for w in WrongQuestion.query.filter_by(
            user_id=current_user.id, is_mastered=True).all()]
        query = query.filter(Question.id.in_(mastered_ids))

    pagination = query.order_by(
        func.random() if app.config.get('SQLALCHEMY_DATABASE_URI', '').find('sqlite') >= 0 else Question.id
    ).paginate(page=page, per_page=per_page, error_out=False)

    questions = [q.to_dict() for q in pagination.items]

    # 标记哪些是错题
    wrong_map = {w.question_id: w for w in WrongQuestion.query.filter_by(user_id=current_user.id).all()}
    for q in questions:
        if q['id'] in wrong_map:
            q['is_wrong'] = True
            q['wrong_count'] = wrong_map[q['id']].wrong_count
            q['is_mastered'] = wrong_map[q['id']].is_mastered
        else:
            q['is_wrong'] = False

    return api_response(True, 'ok', {
        'questions': questions,
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@app.route('/api/questions/<int:qid>')
@login_required
def api_get_question(qid):
    q = db.session.get(Question, qid)
    if not q:
        return api_response(False, '题目不存在', code=404)
    data = q.to_dict()
    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=qid).first()
    if wrong:
        data['is_wrong'] = True
        data['wrong_count'] = wrong.wrong_count
        data['is_mastered'] = wrong.is_mastered
    return api_response(True, 'ok', data)


@app.route('/api/practice', methods=['GET'])
@login_required
def api_practice():
    """获取刷题题目 - 通过推荐算法"""
    subject = request.args.get('subject', 'all')
    count = int(request.args.get('count', 10))
    mode = request.args.get('mode', 'recommend')  # recommend / random / wrong / new / challenge

    question_ids = recommendation.get_practice_questions(
        current_user.id, subject, count, mode)

    result = []
    wrong_map = {w.question_id: w for w in WrongQuestion.query.filter_by(user_id=current_user.id).all()}
    answered_map = {r.question_id: True for r in AnswerRecord.query.filter_by(user_id=current_user.id).all()}

    for qid in question_ids:
        q = db.session.get(Question, qid)
        if not q:
            continue
        data = q.to_dict()
        data['is_wrong'] = qid in wrong_map
        data['is_answered'] = qid in answered_map
        if qid in wrong_map:
            data['wrong_count'] = wrong_map[qid].wrong_count
        result.append(data)

    return api_response(True, 'ok', {'questions': result})


@app.route('/api/submit-answer', methods=['POST'])
@login_required
def api_submit_answer():
    """提交答案"""
    data = request.get_json()
    question_id = data.get('question_id')
    user_answer = data.get('answer', '')
    answer_type = data.get('type', 'single')

    if isinstance(user_answer, list):
        user_answer_str = json.dumps(sorted([str(a) for a in user_answer]))
    else:
        user_answer_str = str(user_answer)

    question = db.session.get(Question, question_id)
    if not question:
        return api_response(False, '题目不存在', code=404)

    is_correct = question.is_correct(user_answer)

    # 记录答题
    record = AnswerRecord(
        user_id=current_user.id,
        question_id=question_id,
        user_answer=user_answer_str,
        is_correct=is_correct,
        date_str=date.today().strftime('%Y-%m-%d')
    )
    db.session.add(record)

    # 更新用户统计
    current_user.total_attempts += 1
    today = date.today().strftime('%Y-%m-%d')

    if is_correct:
        current_user.total_correct += 1
        exp_gain = question.difficulty * 5
        current_user.exp_points += exp_gain
        # 连续打卡 += 1
        if current_user.last_active:
            if current_user.last_active.date() == date.today() - timedelta(days=1):
                current_user.current_streak += 1
            elif current_user.last_active.date() < date.today() - timedelta(days=1):
                current_user.current_streak = 1
        else:
            current_user.current_streak = 1
        current_user.streak_days = max(current_user.streak_days, current_user.current_streak)
        current_user.last_active = datetime.utcnow()

        # 若答对，减少错题计数
        wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question_id).first()
        if wrong:
            wrong.wrong_count = max(0, wrong.wrong_count - 1)
            if wrong.wrong_count == 0:
                wrong.is_mastered = True

        # 更新每日统计
        day_stat = DayStat.query.filter_by(user_id=current_user.id, date_str=today).first()
        if not day_stat:
            day_stat = DayStat(user_id=current_user.id, date_str=today, attempts=0, correct=0, wrong=0, expirence=0)
            db.session.add(day_stat)
        day_stat.attempts = (day_stat.attempts or 0) + 1
        day_stat.correct = (day_stat.correct or 0) + 1
        day_stat.expirence = (day_stat.expirence or 0) + exp_gain

        # 更新科目统计
        update_subject_stats(current_user, question.subject, is_correct=True)

        # 每日打卡：当日做对达标自动发放积分
        checkin_gained = 0
        checkin = DailyCheckin.query.filter_by(user_id=current_user.id, date_str=today).first()
        if not checkin:
            checkin = DailyCheckin(user_id=current_user.id, date_str=today,
                                   correct_count=0, target=10, reward=12, claimed=False)
            db.session.add(checkin)
        checkin.correct_count = (checkin.correct_count or 0) + 1
        if not checkin.claimed and (checkin.correct_count or 0) >= (checkin.target or 10):
            checkin.claimed = True
            checkin.claimed_at = datetime.utcnow()
            reward = checkin.reward or 12
            current_user.points = (current_user.points or 0) + reward
            checkin_gained = reward

        db.session.commit()
        return api_response(True, '回答正确！', {
            'is_correct': True,
            'answer': question.answer,
            'explanation': question.explanation,
            'exp_gained': exp_gain,
            'points_gained': 0,
            'checkin_gained': checkin_gained,
            'points': current_user.points or 0,
            'user_stats': current_user.to_dict()
        })

    else:
        current_user.total_wrong += 1
        current_user.last_active = datetime.utcnow()

        # 记录错题
        wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question_id).first()
        if not wrong:
            wrong = WrongQuestion(user_id=current_user.id, question_id=question_id)
            db.session.add(wrong)
        else:
            wrong.wrong_count += 1
            wrong.is_mastered = False
        wrong.last_wrong_at = datetime.utcnow()

        # 更新每日统计
        day_stat = DayStat.query.filter_by(user_id=current_user.id, date_str=today).first()
        if not day_stat:
            day_stat = DayStat(user_id=current_user.id, date_str=today, attempts=0, correct=0, wrong=0, expirence=0)
            db.session.add(day_stat)
        day_stat.attempts = (day_stat.attempts or 0) + 1
        day_stat.wrong = (day_stat.wrong or 0) + 1

        # 更新科目统计
        update_subject_stats(current_user, question.subject, is_correct=False)

        db.session.commit()
        return api_response(True, '回答错误，再接再厉！', {
            'is_correct': False,
            'answer': question.answer,
            'explanation': question.explanation,
            'exp_gained': 0,
            'user_stats': current_user.to_dict()
        }, 200)


def update_subject_stats(user, subject, is_correct):
    """更新用户科目统计"""
    stats = json.loads(user.subject_stats or '{}')
    if subject not in stats:
        stats[subject] = {'correct': 0, 'total': 0}
    stats[subject]['total'] += 1
    if is_correct:
        stats[subject]['correct'] += 1
    user.subject_stats = json.dumps(stats)


@app.route('/api/similar/<int:question_id>', methods=['GET'])
@login_required
def api_similar(question_id):
    """获取类似题目"""
    count = int(request.args.get('count', 5))
    similar_questions = recommendation.get_similar_questions(question_id, count)
    result = [q.to_dict() for q in similar_questions] if similar_questions else []
    question = db.session.get(Question, question_id)
    source = question.to_dict() if question else None
    return api_response(True, 'ok', {'source_question': source, 'similar': result})


# ===================== 统计API =====================

@app.route('/api/stats/overview')
@login_required
def api_stats_overview():
    """总览统计"""
    user = current_user

    # 该用户答题总数、正确率、错题数、本题数
    wrong_count = WrongQuestion.query.filter_by(user_id=user.id, is_mastered=False).count()
    mastered_count = WrongQuestion.query.filter_by(user_id=user.id, is_mastered=True).count()
    total_questions = Question.query.count()
    user_uploaded = Question.query.filter_by(created_by=user.id).count()

    # 答题趋势（最近7天）
    trend_data = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).strftime('%Y-%m-%d')
        stat = DayStat.query.filter_by(user_id=user.id, date_str=d).first()
        trend_data.append({
            'date': d,
            'attempts': stat.attempts if stat else 0,
            'correct': stat.correct if stat else 0,
            'wrong': stat.wrong if stat else 0
        })

    # 科目表现
    subject_stats = json.loads(user.subject_stats or '{}')

    return api_response(True, 'ok', {
        'user': user.to_dict(),
        'total_attempts': user.total_attempts,
        'total_correct': user.total_correct,
        'total_wrong': user.total_wrong,
        'accuracy': user.get_accuracy(),
        'wrong_count': wrong_count,
        'mastered_count': mastered_count,
        'total_questions': total_questions,
        'user_uploaded': user_uploaded,
        'trend': trend_data,
        'subject_stats': subject_stats
    })


@app.route('/api/stats/subject')
@login_required
def api_stats_subject():
    """各科目正确率"""
    subject_stats = json.loads(current_user.subject_stats or '{}')
    results = []
    for subject, stat in subject_stats.items():
        accuracy = round(stat['correct'] / stat['total'] * 100, 1) if stat['total'] > 0 else 0
        results.append({
            'subject': subject,
            'total': stat['total'],
            'correct': stat['correct'],
            'wrong': stat['total'] - stat['correct'],
            'accuracy': accuracy
        })
    results.sort(key=lambda x: x['accuracy'])
    return api_response(True, 'ok', {'subjects': results})


@app.route('/api/stats/heatmap')
@login_required
def api_stats_heatmap():
    """活跃热力图"""
    stats = DayStat.query.filter_by(user_id=current_user.id).all()
    result = {}
    for s in stats:
        result[s.date_str] = {
            'attempts': s.attempts,
            'correct': s.correct,
            'wrong': s.wrong
        }
    return api_response(True, 'ok', {'days': result})


# ===================== 错题本API =====================

@app.route('/api/wrong-questions')
@login_required
def api_wrong_questions():
    subject = request.args.get('subject', 'all')
    is_mastered = request.args.get('is_mastered', 'false')

    query = WrongQuestion.query.filter_by(user_id=current_user.id)
    if is_mastered == 'true':
        query = query.filter_by(is_mastered=True)
    else:
        query = query.filter_by(is_mastered=False)

    wrongs = query.order_by(WrongQuestion.last_wrong_at.desc()).all()
    q_ids = [w.question_id for w in wrongs]
    questions = Question.query.filter(Question.id.in_(q_ids)).all() if q_ids else []

    if subject and subject != 'all':
        questions = [q for q in questions if q.subject == subject]

    q_map = {q.id: q for q in questions}
    result = []
    for w in wrongs:
        if w.question_id in q_map:
            q = q_map[w.question_id]
            data = q.to_dict()
            data['wrong_count'] = w.wrong_count
            data['last_wrong_at'] = w.last_wrong_at.strftime('%Y-%m-%d %H:%M') if w.last_wrong_at else ''
            data['is_mastered'] = w.is_mastered
            result.append(data)

    total_wrong = WrongQuestion.query.filter_by(user_id=current_user.id, is_mastered=False).count()
    total_mastered = WrongQuestion.query.filter_by(user_id=current_user.id, is_mastered=True).count()

    return api_response(True, 'ok', {
        'wrong_questions': result,
        'total_wrong': total_wrong,
        'total_mastered': total_mastered
    })


@app.route('/api/wrong-questions/<int:qid>/mastered', methods=['POST'])
@login_required
def api_mark_mastered(qid):
    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=qid).first()
    if not wrong:
        return api_response(False, '该题不在错题本中', code=404)
    wrong.is_mastered = True
    wrong.wrong_count = 0
    db.session.commit()
    return api_response(True, '已标记为掌握')


@app.route('/api/wrong-questions/<int:qid>', methods=['DELETE'])
@login_required
def api_delete_wrong(qid):
    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=qid).first()
    if not wrong:
        return api_response(False, '该题不在错题本中', code=404)
    db.session.delete(wrong)
    db.session.commit()
    return api_response(True, '已从错题本移除')


# ===================== 上传API =====================

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if 'file' not in request.files:
        return api_response(False, '没有选择文件', code=400)

    file = request.files['file']
    subject = request.form.get('subject', '')
    if not file or file.filename == '':
        return api_response(False, '没有选择文件', code=400)

    if not subject:
        return api_response(False, '请选择科目', code=400)

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.docx'):
        return api_response(False, '仅支持上传 .docx 格式的Word文档', code=400)

    # 保存文件到临时目录
    if not os.path.exists(Config.UPLOAD_FOLDER):
        os.makedirs(Config.UPLOAD_FOLDER)

    saved_path = os.path.join(Config.UPLOAD_FOLDER, f'{uuid.uuid4().hex}_{filename}')
    file.save(saved_path)

    log = UploadLog(
        user_id=current_user.id,
        filename=filename,
        subject=subject
    )
    db.session.add(log)
    db.session.flush()

    try:
        questions = word_parser.parse_docx(saved_path, subject, current_user.id)
        imported = 0
        failed = []

        for q in questions:
            new_q = Question(
                subject=subject,
                topic=q.get('topic', '用户上传'),
                difficulty=q.get('difficulty', 2),
                type=q.get('type', 'single'),
                content=q['content'],
                options=json.dumps(q.get('options', []), ensure_ascii=False),
                answer=json.dumps(q.get('answer'), ensure_ascii=False),
                explanation=q.get('explanation', ''),
                tags=q.get('tags', '用户上传'),
                keywords=q.get('tags', ''),
                created_by=current_user.id,
                source='upload'
            )
            db.session.add(new_q)
            imported += 1

        log.total_questions = len(questions)
        log.imported_count = imported
        log.status = 'success'
        db.session.commit()

        return api_response(True, f'上传成功，共导入 {imported} 道题', {
            'imported': imported,
            'failed': failed
        })

    except Exception as e:
        log.status = 'failed'
        db.session.commit()
        return api_response(False, f'解析失败: {str(e)}', code=500)
    finally:
        try:
            os.remove(saved_path)
        except:
            pass


@app.route('/api/my-uploads')
@login_required
def api_my_uploads():
    logs = UploadLog.query.filter_by(user_id=current_user.id).order_by(
        UploadLog.created_at.desc()).limit(20).all()
    result = [{
        'id': log.id,
        'filename': log.filename,
        'subject': log.subject,
        'total_questions': log.total_questions,
        'imported_count': log.imported_count,
        'status': log.status,
        'created_at': log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else ''
    } for log in logs]
    return api_response(True, 'ok', {'logs': result})


# ===================== 手动添加题目 =====================

def normalize_manual_answer(raw, qtype):
    """规范化手动录入答案：
    single -> 'B'，multi -> ['A','B']，true_false -> '对'/'错'
    """
    raw = (raw or '').strip()
    if qtype == 'true_false':
        if raw in ('对', '正确', '√', '是', 'T', 'true', 'True'):
            return '对'
        if raw in ('错', '错误', '×', '否', 'F', 'false', 'False'):
            return '错'
        raise ValueError('判断题答案必须是对或错')

    letters = list(dict.fromkeys(re.findall(r'[A-H]', raw.upper())))
    if not letters:
        return None
    return letters if qtype == 'multi' else letters[0]


@app.route('/api/questions', methods=['POST'])
@login_required
def api_create_question():
    """网页手动添加题目（可归入自定义题库）"""
    data = request.get_json()
    subject = (data.get('subject') or '').strip()
    topic = (data.get('topic') or '').strip()
    difficulty = int(data.get('difficulty', 2))
    qtype = (data.get('type') or 'single').strip()
    content = (data.get('content') or '').strip()
    options_raw = data.get('options') or []
    answer_raw = (data.get('answer') or '').strip()
    explanation = (data.get('explanation') or '').strip()
    tags = (data.get('tags') or '').strip()
    bank_id = data.get('bank_id')

    bank = None
    if bank_id:
        bank = db.session.get(QuestionBank, int(bank_id))
        if not bank or bank.owner_id != current_user.id:
            return api_response(False, '题库不存在或无权操作', code=403)

    if subject not in SUBJECTS:
        return api_response(False, f'请选择有效科目（{" / ".join(SUBJECTS)}）', code=400)
    if not content:
        return api_response(False, '题目内容不能为空', code=400)
    if qtype not in ('single', 'multi', 'true_false'):
        return api_response(False, '题目类型无效', code=400)
    if difficulty not in (1, 2, 3):
        return api_response(False, '难度参数无效', code=400)

    options = []
    if qtype == 'true_false':
        try:
            answer = normalize_manual_answer(answer_raw, qtype)
        except ValueError as e:
            return api_response(False, str(e), code=400)
    else:
        cleaned = [str(o).strip() for o in options_raw if str(o).strip()][:8]
        if len(cleaned) < 2:
            return api_response(False, f'{"多选" if qtype == "multi" else "单选"}题至少需要2个选项', code=400)
        letters = [chr(65 + i) for i in range(len(cleaned))]
        options = [f'{letters[i]}. {cleaned[i]}' for i in range(len(cleaned))]
        answer = normalize_manual_answer(answer_raw, qtype)
        if not answer:
            return api_response(False, '请选择正确答案（单选题填选项字母，多选题填如 A,B,C）', code=400)

    question = Question(
        subject=subject,
        topic=topic or '用户添加',
        difficulty=difficulty,
        type=qtype,
        content=content,
        options=json.dumps(options, ensure_ascii=False),
        answer=json.dumps(answer, ensure_ascii=False),
        explanation=explanation,
        tags=tags or '用户添加',
        keywords=tags or '',
        created_by=current_user.id,
        is_approved=True,
        source='manual',
        bank_id=bank.id if bank else None
    )
    db.session.add(question)
    db.session.commit()
    return api_response(True, '题目添加成功，可立即开始刷题', {'question': question.to_dict()}, 201)


@app.route('/api/my-questions')
@login_required
def api_my_questions():
    """当前用户添加的题目列表"""
    questions = Question.query.filter_by(created_by=current_user.id).order_by(
        Question.created_at.desc()).limit(200).all()
    return api_response(True, 'ok', {
        'questions': [q.to_dict() for q in questions]
    })


@app.route('/api/questions/<int:qid>', methods=['DELETE'])
@login_required
def api_delete_question(qid):
    """删除自己创建的题目"""
    q = db.session.get(Question, qid)
    if not q:
        return api_response(False, '题目不存在', code=404)
    if q.created_by != current_user.id:
        return api_response(False, '只能删除自己添加的题目', code=403)
    db.session.delete(q)
    db.session.commit()
    return api_response(True, '题目已删除')


# ===================== 考试API =====================

def gen_exam_code():
    """生成唯一考试码"""
    charset = string.ascii_uppercase + string.digits
    for _ in range(200):
        code = ''.join(random.choices(charset, k=6))
        if not Exam.query.filter_by(exam_code=code).first():
            return code
    return uuid.uuid4().hex[:8].upper()


@app.route('/api/exams', methods=['GET'])
@login_required
def api_exams():
    exams = Exam.query.filter_by(creator_id=current_user.id).order_by(
        Exam.created_at.desc()).all()
    return api_response(True, 'ok', {'exams': [e.to_dict(True) for e in exams]})


@app.route('/api/exams', methods=['POST'])
@login_required
def api_create_exam():
    """创建考试：名称/科目/题源/数量/限时/满分/合格分/考生字段"""
    data = request.get_json()
    name = (data.get('name') or '').strip()
    subject = (data.get('subject') or '').strip()
    source = (data.get('source') or 'system').strip()
    question_count = int(data.get('question_count') or 10)
    duration_minutes = int(data.get('duration_minutes') or 30)
    total_score = int(data.get('total_score') or 100)
    pass_score = int(data.get('pass_score') or 60)
    description = (data.get('description') or '').strip()

    if not name:
        return api_response(False, '考试名称不能为空', code=400)
    if subject not in SUBJECTS:
        return api_response(False, '请选择有效的科目', code=400)
    if source not in ('system', 'mine'):
        return api_response(False, '题源无效', code=400)
    if question_count < 1 or question_count > 100:
        return api_response(False, '题目数量需在 1-100 之间', code=400)
    if duration_minutes < 1 or duration_minutes > 600:
        return api_response(False, '考试时长需在 1-600 分钟之间', code=400)
    if total_score <= 0 or pass_score <= 0 or pass_score > total_score:
        return api_response(False, '满分与合格分数设置不合理', code=400)

    # 考生信息字段
    raw_fields = data.get('candidate_fields') or []
    fields = []
    seen = set()
    for f in raw_fields:
        key = str(f.get('key') or '').strip()
        label = str(f.get('label') or '').strip()
        if not key or not label or key in seen:
            continue
        seen.add(key)
        fields.append({
            'key': key,
            'label': label,
            'required': bool(f.get('required', False)),
            'type': f.get('type') or 'text'
        })
    if not fields:
        fields = [{'key': 'name', 'label': '姓名', 'required': True, 'type': 'text'}]

    # 按题源筛选题目池
    if source == 'mine':
        pool = Question.query.filter(Question.subject == subject, Question.created_by == current_user.id)
    else:
        pool = Question.query.filter(Question.subject == subject, Question.bank_id.is_(None))
    available = pool.count()
    if available == 0:
        return api_response(False, '所选「题源+科目」下暂无可用题目，请先添加题目或换科目', code=400)
    if available < question_count:
        question_count = available

    picked = pool.order_by(func.random()).limit(question_count).all()
    exam = Exam(
        name=name,
        exam_code=gen_exam_code(),
        creator_id=current_user.id,
        subject=subject,
        source=source,
        question_count=len(picked),
        duration_minutes=duration_minutes,
        total_score=total_score,
        pass_score=pass_score,
        candidate_fields=json.dumps(fields, ensure_ascii=False),
        description=description
    )
    db.session.add(exam)
    db.session.flush()

    per_score = round(total_score / question_count, 2)
    for i, q in enumerate(picked):
        db.session.add(ExamQuestion(
            exam_id=exam.id, question_id=q.id, score=per_score, ordering=i))

    db.session.commit()
    return api_response(True, f'考试创建成功，共 {len(picked)} 道题', {'exam': exam.to_dict(True)}, 201)


@app.route('/api/exams/<int:exam_id>')
@login_required
def api_exam_detail(exam_id):
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return api_response(False, '考试不存在', code=404)
    return api_response(True, 'ok', {'exam': exam.to_dict(True)})


@app.route('/api/exams/<int:exam_id>', methods=['DELETE'])
@login_required
def api_delete_exam(exam_id):
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return api_response(False, '考试不存在', code=404)
    if exam.creator_id != current_user.id:
        return api_response(False, '只能删除自己发起的考试', code=403)
    ExamQuestion.query.filter_by(exam_id=exam.id).delete()
    ExamResult.query.filter_by(exam_id=exam.id).delete()
    db.session.delete(exam)
    db.session.commit()
    return api_response(True, '考试已删除')


@app.route('/api/exam/<exam_code>/start', methods=['POST'])
@login_required
def api_exam_start(exam_code):
    """考生凭考试码开始考试：校验考生信息，返回题目（不含答案）"""
    exam = Exam.query.filter_by(exam_code=exam_code).first()
    if not exam:
        return api_response(False, '考试不存在或链接无效', code=404)

    dup = ExamResult.query.filter_by(exam_id=exam.id, taker_id=current_user.id).first()
    if dup:
        return api_response(False, '你已完成该考试，不能重复参加', code=400)

    data = request.get_json() or {}
    candidate = data.get('candidate_info') or {}
    fields = json.loads(exam.candidate_fields or '[]')
    filled = {}
    for f in fields:
        val = (candidate.get(f['key']) or '').strip()
        if f.get('required') and not val:
            return api_response(False, f'请填写考生信息：{f["label"]}', code=400)
        filled[f['key']] = val

    eqs = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.ordering).all()
    if not eqs:
        return api_response(False, '该考试暂无题目', code=400)

    questions = []
    for eq in eqs:
        q = db.session.get(Question, eq.question_id)
        if not q:
            continue
        d = q.to_dict()
        d.pop('answer', None)
        d['score'] = eq.score
        d['ordering'] = eq.ordering
        questions.append(d)

    return api_response(True, '考试开始，祝你顺利！', {
        'code': exam.exam_code,
        'name': exam.name,
        'subject': exam.subject,
        'duration_minutes': exam.duration_minutes,
        'total_score': exam.total_score,
        'pass_score': exam.pass_score,
        'candidate_info': filled,
        'questions': questions
    })


@app.route('/api/exam/<exam_code>/submit', methods=['POST'])
@login_required
def api_exam_submit(exam_code):
    """交卷自动评分"""
    exam = Exam.query.filter_by(exam_code=exam_code).first()
    if not exam:
        return api_response(False, '考试不存在', code=404)

    dup = ExamResult.query.filter_by(exam_id=exam.id, taker_id=current_user.id).first()
    if dup:
        return api_response(False, '你已完成该考试，不能重复提交', code=400)

    data = request.get_json() or {}
    answers = data.get('answers') or {}
    candidate = data.get('candidate_info') or {}
    time_used = int(data.get('time_used_seconds') or 0)

    eqs = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.ordering).all()
    correct = 0
    score = 0.0
    checked = {}
    for eq in eqs:
        q = db.session.get(Question, eq.question_id)
        if not q:
            continue
        submitted = answers.get(str(eq.question_id))
        ok = q.is_correct(submitted)
        checked[str(eq.question_id)] = {
            'question_id': q.id,
            'content': q.content,
            'type': q.type,
            'your_answer': submitted if submitted else '',
            'correct_answer': json.loads(q.answer),
            'explanation': q.explanation,
            'is_correct': ok,
            'score': eq.score
        }
        if ok:
            correct += 1
            score += eq.score

    score = round(score, 2)
    passed = score >= exam.pass_score
    started_at = datetime.utcnow() - timedelta(seconds=time_used)

    result = ExamResult(
        exam_id=exam.id,
        taker_id=current_user.id,
        candidate_info=json.dumps(candidate, ensure_ascii=False),
        answers=json.dumps(checked, ensure_ascii=False),
        score=score,
        total_score=exam.total_score,
        correct_count=correct,
        question_count=len(eqs),
        passed=passed,
        status='graded',
        started_at=started_at,
        submitted_at=datetime.utcnow(),
        time_used_seconds=time_used
    )
    db.session.add(result)
    db.session.commit()

    return api_response(True, '交卷成功', {
        'result': result.to_dict(),
        'per_question': checked
    })


@app.route('/api/exam-attempts')
@login_required
def api_exam_attempts():
    """当前用户作为考生参加过的考试"""
    results = ExamResult.query.filter_by(taker_id=current_user.id).order_by(
        ExamResult.submitted_at.desc()).limit(50).all()
    out = []
    for r in results:
        exam = db.session.get(Exam, r.exam_id)
        if not exam:
            continue
        d = r.to_dict()
        d['exam_name'] = exam.name
        d['exam_code'] = exam.exam_code
        d['subject'] = exam.subject
        d['pass_score'] = exam.pass_score
        out.append(d)
    return api_response(True, 'ok', {'attempts': out})


@app.route('/api/exams/<int:exam_id>/results')
@login_required
def api_exam_results(exam_id):
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return api_response(False, '考试不存在', code=404)
    if exam.creator_id != current_user.id:
        return api_response(False, '只能查看自己发起的考试结果', code=403)
    results = ExamResult.query.filter_by(exam_id=exam_id).order_by(
        ExamResult.submitted_at.desc()).all()
    return api_response(True, 'ok', {'results': [r.to_dict() for r in results]})


@app.route('/api/exams/<int:exam_id>/results/<int:result_id>', methods=['POST'])
@login_required
def api_review_exam_result(exam_id, result_id):
    """人工复核：调整通过状态并备注"""
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return api_response(False, '考试不存在', code=404)
    if exam.creator_id != current_user.id:
        return api_response(False, '无权操作', code=403)
    result = db.session.get(ExamResult, result_id)
    if not result or result.exam_id != exam_id:
        return api_response(False, '成绩记录不存在', code=404)
    data = request.get_json() or {}
    if 'passed' in data:
        result.passed = bool(data['passed'])
    result.status = 'reviewed'
    result.review_note = (data.get('note') or '').strip()
    db.session.commit()
    return api_response(True, '已复核', {'result': result.to_dict()})


# ===================== 题库API =====================

@app.route('/api/banks', methods=['GET'])
@login_required
def api_banks():
    """题库列表：可搜索公开题库，也可只看自己创建的"""
    keyword = (request.args.get('keyword') or '').strip()
    mine = request.args.get('mine') == '1'

    query = QuestionBank.query
    if mine:
        query = query.filter(QuestionBank.owner_id == current_user.id)
    else:
        query = query.filter(or_(QuestionBank.is_public == True,
                                 QuestionBank.owner_id == current_user.id))
    if keyword:
        query = query.filter(or_(
            QuestionBank.name.contains(keyword),
            QuestionBank.description.contains(keyword)
        ))
    banks = query.order_by(QuestionBank.created_at.desc()).limit(200).all()
    mine_count = QuestionBank.query.filter_by(owner_id=current_user.id).count()
    return api_response(True, 'ok', {
        'banks': [b.to_dict() for b in banks],
        'mine_count': mine_count,
        'max_per_user': QuestionBank.MAX_PER_USER
    })


@app.route('/api/banks', methods=['POST'])
@login_required
def api_create_bank():
    """创建题库（每用户最多450个）"""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    is_public = bool(data.get('is_public', True))
    if not name:
        return api_response(False, '题库名称不能为空', code=400)
    if len(name) > 100:
        return api_response(False, '题库名称不能超过100个字符', code=400)

    count = QuestionBank.query.filter_by(owner_id=current_user.id).count()
    if count >= QuestionBank.MAX_PER_USER:
        return api_response(False, f'每个用户最多创建{QuestionBank.MAX_PER_USER}个题库', code=400)

    bank = QuestionBank(name=name, description=description,
                        owner_id=current_user.id, is_public=is_public)
    db.session.add(bank)
    db.session.commit()
    return api_response(True, '题库创建成功', {'bank': bank.to_dict()}, 201)


@app.route('/api/banks/<int:bank_id>')
@login_required
def api_bank_detail(bank_id):
    """题库详情（含题目列表）"""
    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return api_response(False, '题库不存在', code=404)
    if not bank.is_public and bank.owner_id != current_user.id:
        return api_response(False, '无权查看该题库', code=403)
    questions = Question.query.filter_by(bank_id=bank_id).order_by(
        Question.created_at.desc()).limit(500).all()
    return api_response(True, 'ok', {
        'bank': bank.to_dict(),
        'questions': [q.to_dict() for q in questions]
    })


@app.route('/api/banks/<int:bank_id>', methods=['DELETE'])
@login_required
def api_delete_bank(bank_id):
    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return api_response(False, '题库不存在', code=404)
    if bank.owner_id != current_user.id:
        return api_response(False, '只能删除自己创建的题库', code=403)
    Question.query.filter_by(bank_id=bank_id).delete()
    db.session.delete(bank)
    db.session.commit()
    return api_response(True, '题库已删除')


@app.route('/api/bank/<int:bank_id>/practice')
@login_required
def api_bank_practice(bank_id):
    """从题库抽题练习"""
    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return api_response(False, '题库不存在', code=404)
    if not bank.is_public and bank.owner_id != current_user.id:
        return api_response(False, '无权练习该题库', code=403)
    count = int(request.args.get('count', 10))
    questions = Question.query.filter_by(bank_id=bank_id).order_by(
        func.random()).limit(count).all()
    return api_response(True, 'ok', {
        'bank': bank.to_dict(),
        'questions': [q.to_dict() for q in questions]
    })


# ===================== 积分API =====================

KEY_REDEEM_POINTS = 20
KEY_REDEEM_COUNT = 8


@app.route('/api/points')
@login_required
def api_points():
    """积分中心：余额、每日打卡状态、可换重点题、已解锁重点题"""
    today = date.today().strftime('%Y-%m-%d')
    checkin = DailyCheckin.query.filter_by(user_id=current_user.id, date_str=today).first()

    owned_sub = db.session.query(UserKeyQuestion.question_id).filter_by(user_id=current_user.id)
    pool_size = Question.query.filter(
        Question.is_key == True,
        Question.bank_id.is_(None),
        ~Question.id.in_(owned_sub)
    ).count()

    unlocked = UserKeyQuestion.query.filter_by(user_id=current_user.id).all()
    qs = (Question.query.filter(Question.id.in_([u.question_id for u in unlocked])).all()
          if unlocked else [])
    latest = DailyCheckin.query.filter_by(
        user_id=current_user.id, claimed=True).order_by(
        DailyCheckin.claimed_at.desc()).first()

    return api_response(True, 'ok', {
        'points': current_user.points or 0,
        'checkin': {
            'date': today,
            'correct_count': checkin.correct_count if checkin else 0,
            'target': (checkin.target if checkin else 10),
            'reward': (checkin.reward if checkin else 12),
            'claimed': checkin.claimed if checkin else False,
            'last_claimed': latest.date_str if latest else ''
        },
        'redeem': {
            'cost': KEY_REDEEM_POINTS,
            'count': KEY_REDEEM_COUNT,
            'available_pool': pool_size
        },
        'key_questions': [q.to_dict() for q in qs]
    })


@app.route('/api/points/exchange', methods=['POST'])
@login_required
def api_exchange_key():
    """积分换重点题：20积分换8题"""
    if (current_user.points or 0) < KEY_REDEEM_POINTS:
        need = KEY_REDEEM_POINTS - (current_user.points or 0)
        return api_response(False, f'积分不足，还差 {need} 积分（每日做对10题领12积分）', code=400)

    owned_sub = db.session.query(UserKeyQuestion.question_id).filter_by(user_id=current_user.id)
    pool = Question.query.filter(
        Question.is_key == True,
        Question.bank_id.is_(None),
        ~Question.id.in_(owned_sub)
    ).order_by(func.random()).limit(KEY_REDEEM_COUNT).all()
    if len(pool) < KEY_REDEEM_COUNT:
        return api_response(False, '重点题池暂时不足，请稍后再试', code=400)

    current_user.points = (current_user.points or 0) - KEY_REDEEM_POINTS
    for q in pool:
        db.session.add(UserKeyQuestion(user_id=current_user.id, question_id=q.id))
    db.session.commit()
    return api_response(True, f'兑换成功，已解锁 {len(pool)} 道重点题，可在刷题页练习', {
        'questions': [q.to_dict() for q in pool],
        'points': current_user.points or 0
    }, 201)


# ===================== 联机API =====================

match_lock = Lock()


def gen_room_code():
    charset = string.ascii_uppercase + string.digits
    for _ in range(300):
        code = ''.join(random.choices(charset, k=6))
        if not MatchRoom.query.filter_by(room_code=code).first():
            return code
    return uuid.uuid4().hex[:8].upper()


@app.route('/api/match/rooms', methods=['GET'])
@login_required
def api_match_rooms():
    """开放房间列表（等待/进行中）"""
    rooms = MatchRoom.query.filter(
        MatchRoom.status.in_(['waiting', 'active'])).order_by(
        MatchRoom.created_at.desc()).limit(50).all()
    return api_response(True, 'ok', {'rooms': [r.to_dict() for r in rooms]})


@app.route('/api/match/rooms', methods=['POST'])
@login_required
def api_create_room():
    """创建联机房间，题目来自官方题库"""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    subject = (data.get('subject') or '').strip()
    question_count = int(data.get('count') or 10)
    if not name:
        return api_response(False, '房间名称不能为空', code=400)
    if subject not in SUBJECTS:
        return api_response(False, '请选择有效科目', code=400)
    if question_count < 1 or question_count > 50:
        return api_response(False, '题目数量需在 1-50 之间', code=400)

    pool = Question.query.filter(
        Question.subject == subject, Question.bank_id.is_(None)
    ).order_by(func.random()).limit(question_count).all()
    if not pool:
        return api_response(False, '该科目没有可用题目', code=400)
    question_count = len(pool)

    room = MatchRoom(
        room_code=gen_room_code(),
        name=name,
        host_id=current_user.id,
        subject=subject,
        question_count=question_count,
        question_ids=json.dumps([q.id for q in pool]),
        status='waiting'
    )
    db.session.add(room)
    db.session.flush()
    db.session.add(MatchPlayer(room_id=room.id, user_id=current_user.id))
    db.session.commit()
    return api_response(True, '房间创建成功，把房间码发给对手吧', {'room': room.to_dict()}, 201)


@app.route('/api/match/rooms/<code>/join', methods=['POST'])
@login_required
def api_join_room(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在或已关闭', code=404)
    if room.status == 'finished':
        return api_response(False, '该房间比赛已结束', code=400)

    player = MatchPlayer.query.filter_by(room_id=room.id, user_id=current_user.id).first()
    if not player:
        player = MatchPlayer(room_id=room.id, user_id=current_user.id)
        db.session.add(player)
        db.session.commit()
    return api_response(True, '加入成功', {'room': room.to_dict()})


@app.route('/api/match/rooms/<code>/start', methods=['POST'])
@login_required
def api_start_room(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在', code=404)
    if room.host_id != current_user.id:
        return api_response(False, '只有房主可以开始比赛', code=403)
    if room.status != 'waiting':
        return api_response(False, '房间已开始或已结束', code=400)
    room.status = 'active'
    room.current_order = 0
    db.session.commit()
    return api_response(True, '比赛开始！', {'room': room.to_dict()})


@app.route('/api/match/rooms/<code>/state')
@login_required
def api_room_state(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在', code=404)
    players = MatchPlayer.query.filter_by(room_id=room.id).all()
    p_list = []
    for p in players:
        u = db.session.get(User, p.user_id)
        p_list.append({
            'user_id': p.user_id,
            'username': u.username if u else '?',
            'score': p.score,
            'correct_count': p.correct_count,
            'answered_count': p.answered_count,
            'is_me': p.user_id == current_user.id,
        })
    p_list.sort(key=lambda x: x['score'], reverse=True)
    return api_response(True, 'ok', {
        'room': room.to_dict(),
        'players': p_list,
        'in_room': MatchPlayer.query.filter_by(room_id=room.id, user_id=current_user.id).first() is not None,
        'is_host': room.host_id == current_user.id,
        'question_ids': json.loads(room.question_ids or '[]')
    })


@app.route('/api/match/rooms/<code>/question')
@login_required
def api_room_question(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在', code=404)
    player = MatchPlayer.query.filter_by(room_id=room.id, user_id=current_user.id).first()
    if not player:
        return api_response(False, '请先加入房间', code=403)
    if room.status == 'finished':
        return api_response(False, '比赛已结束', code=400)
    ids = json.loads(room.question_ids or '[]')
    order = room.current_order
    if room.status != 'active':
        return api_response(True, '房间等待中', {
            'status': room.status, 'question': None})
    if order >= len(ids):
        return api_response(False, '比赛已结束', code=400)

    q = db.session.get(Question, ids[order])
    if not q:
        return api_response(False, '题目不存在', code=404)
    d = q.to_dict()
    d.pop('answer', None)
    d['order'] = order
    d['question_number'] = order + 1
    d['total'] = len(ids)

    ans = MatchAnswer.query.filter_by(
        room_id=room.id, user_id=current_user.id, order=order).first()
    d['already_answered'] = ans is not None
    if ans:
        d['correct_answer'] = q.get_answers()[0]
        d['is_correct'] = ans.is_correct

    return api_response(True, 'ok', {
        'status': room.status,
        'current_order': order,
        'question': d
    })


@app.route('/api/match/rooms/<code>/answer', methods=['POST'])
@login_required
def api_room_answer(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在', code=404)
    player = MatchPlayer.query.filter_by(room_id=room.id, user_id=current_user.id).first()
    if not player:
        return api_response(False, '请先加入房间', code=403)
    if room.status != 'active':
        return api_response(False, '比赛尚未开始', code=400)
    data = request.get_json() or {}
    order = int(data.get('order') if data.get('order') is not None else room.current_order)
    answer = data.get('answer')
    ids = json.loads(room.question_ids or '[]')
    if order < 0 or order >= len(ids):
        return api_response(False, '题目序号无效', code=400)
    if order > room.current_order:
        return api_response(False, '还没轮到该题', code=400)

    existing = MatchAnswer.query.filter_by(
        room_id=room.id, user_id=current_user.id, order=order).first()
    if existing:
        ok = existing.is_correct
    else:
        q = db.session.get(Question, ids[order])
        ok = q.is_correct(answer) if q else False
        db.session.add(MatchAnswer(
            room_id=room.id, user_id=current_user.id,
            question_id=ids[order], order=order, is_correct=ok))
        player.answered_count = (player.answered_count or 0) + 1
        if ok:
            player.score = (player.score or 0) + 10
            player.correct_count = (player.correct_count or 0) + 1
        db.session.flush()

    # 全部玩家作答完成 或 距首答超20秒 时推进下一题
    with match_lock:
        room = db.session.get(MatchRoom, room.id)
        if room.status == 'active' and order == room.current_order:
            total_players = MatchPlayer.query.filter_by(room_id=room.id).count()
            answered_now = MatchAnswer.query.filter_by(
                room_id=room.id, order=order).count()
            first_ans = MatchAnswer.query.filter_by(
                room_id=room.id, order=order).order_by(
                MatchAnswer.submitted_at.asc()).first()
            elapsed = ((datetime.utcnow() - first_ans.submitted_at).total_seconds()
                       if first_ans else 0)
            if total_players > 0 and (answered_now >= total_players or elapsed >= 20):
                room.current_order += 1
                if room.current_order >= len(ids):
                    room.status = 'finished'
    db.session.commit()

    return api_response(True, '已提交', {
        'is_correct': ok,
        'current_order': room.current_order,
        'finished': room.status == 'finished'
    })


@app.route('/api/match/rooms/<code>/result')
@login_required
def api_room_result(code):
    room = MatchRoom.query.filter_by(room_code=code).first()
    if not room:
        return api_response(False, '房间不存在', code=404)
    players = MatchPlayer.query.filter_by(room_id=room.id).all()
    p_list = []
    for p in players:
        u = db.session.get(User, p.user_id)
        p_list.append({
            'username': u.username if u else '?',
            'score': p.score,
            'correct_count': p.correct_count,
            'answered_count': p.answered_count,
            'is_me': p.user_id == current_user.id
        })
    p_list.sort(key=lambda x: x['score'], reverse=True)
    return api_response(True, 'ok', {'room': room.to_dict(), 'players': p_list})


# ===================== 排行榜 =====================

@app.route('/api/leaderboard')
@login_required
def api_leaderboard():
    """经验值排行榜"""
    users = User.query.order_by(User.exp_points.desc()).limit(20).all()
    result = []
    rank = 0
    for i, u in enumerate(users):
        rank = i + 1
        result.append({
            'rank': rank,
            'username': u.username,
            'exp_points': u.exp_points,
            'accuracy': u.get_accuracy(),
            'total_attempts': u.total_attempts,
            'is_current': u.id == current_user.id
        })
    return api_response(True, 'ok', {'leaderboard': result})


@app.route('/api/user/stats')
@login_required
def api_user_stats():
    """当前用户的完整统计"""
    return api_stats_overview()


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return api_response(False, '接口不存在', code=404)
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return api_response(False, '服务器内部错误', code=500)


if __name__ == '__main__':
    from init_db import init_database
    init_database(app)
    print('* 浩威刷题平台启动中...')
    print('* 访问地址: http://127.0.0.1:5000')
    app.run(debug=True, host='0.0.0.0', port=5000)
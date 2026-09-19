from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json

db = SQLAlchemy()

# 科目列表
SUBJECTS = [
    'Python', 'C语言', 'C++', 'C#', 'Java',
    '前端', 'JavaScript', 'Node.js', '算法', '数据结构', '后端',
    '计算机原理', '大模型训练', 'vibe coding',
    'SQL', '计算机一级', '计算机二级', '计算机三级',
    '真实开发场景模拟(C/C++)', '真实开发场景模拟(C#/Java)'
]

DIFFICULTY_LEVELS = ['简单', '中等', '困难']


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(20), default='default')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 统计数据
    total_attempts = db.Column(db.Integer, default=0)
    total_correct = db.Column(db.Integer, default=0)
    total_wrong = db.Column(db.Integer, default=0)
    accuracy_rate = db.Column(db.Float, default=0.0)
    streak_days = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    exp_points = db.Column(db.Integer, default=0)
    current_streak = db.Column(db.Integer, default=0)
    points = db.Column(db.Integer, default=0)          # 积分（可换重点题）

    # 每科正确率统计 (JSON: {subject_name: {'correct': x, 'total': y}})
    subject_stats = db.Column(db.Text, default='{}')

    # 关系
    attempts = db.relationship('AnswerRecord', backref='user', lazy='dynamic',
                               cascade='all, delete-orphan')
    wrong_questions = db.relationship('WrongQuestion', backref='user', lazy='dynamic',
                                      cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_accuracy(self):
        if self.total_attempts == 0:
            return 0.0
        return round(self.total_correct / self.total_attempts * 100, 1)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'total_attempts': self.total_attempts,
            'total_correct': self.total_correct,
            'total_wrong': self.total_wrong,
            'accuracy_rate': self.get_accuracy(),
            'streak_days': self.streak_days,
            'current_streak': self.current_streak,
            'exp_points': self.exp_points,
            'points': self.points or 0,
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else '',
            'last_active': self.last_active.strftime('%Y-%m-%d %H:%M') if self.last_active else ''
        }


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(50), nullable=False, index=True)
    topic = db.Column(db.String(100), default='')           # 知识点/主题
    difficulty = db.Column(db.Integer, default=1)            # 1-简单, 2-中等, 3-困难
    type = db.Column(db.String(20), default='single')        # single-单选, multi-多选, true_false-判断

    content = db.Column(db.Text, nullable=False)             # 题干
    options = db.Column(db.Text)                             # JSON数组格式选项
    answer = db.Column(db.Text, nullable=False)              # 正确答案 (JSON或字符串)
    explanation = db.Column(db.Text, default='')             # 答案解析

    # 相似题标签（用于推荐类似题目），格式: 关键词用逗号分隔
    tags = db.Column(db.String(500), default='')
    keywords = db.Column(db.String(500), default='')

    created_by = db.Column(db.Integer, default=0)            # 0表示系统题，否则为用户ID
    is_approved = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    source = db.Column(db.String(50), default='system')      # system / upload

    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=True,
                        index=True)          # 所属题库；NULL表示官方题库
    is_key = db.Column(db.Boolean, default=False)            # 是否重点题（积分可兑换）

    answer_records = db.relationship('AnswerRecord', backref='question', lazy='dynamic',
                                     cascade='all, delete-orphan')

    def get_options(self):
        import json
        try:
            return json.loads(self.options) if self.options else []
        except:
            return []

    def get_answers(self):
        """返回正确答案列表（多选题返回多个）"""
        import json
        try:
            ans = json.loads(self.answer)
            if isinstance(ans, list):
                return [str(a) for a in ans]
            return [str(ans)]
        except:
            return [str(self.answer)]

    def is_correct(self, user_answer):
        """判断用户答案是否正确"""
        if not user_answer:
            return False
        correct = self.get_answers()
        user_ans = user_answer if isinstance(user_answer, list) else [user_answer]
        user_ans = sorted([str(a) for a in user_ans])
        correct = sorted(correct)
        return user_ans == correct

    def to_dict(self):
        return {
            'id': self.id,
            'subject': self.subject,
            'topic': self.topic,
            'difficulty': self.difficulty,
            'difficulty_label': DIFFICULTY_LEVELS[self.difficulty - 1] if 0 < self.difficulty <= 3 else '中等',
            'type': self.type,
            'type_label': {'single': '单选题', 'multi': '多选题', 'true_false': '判断题'}.get(self.type, '单选题'),
            'content': self.content,
            'options': self.get_options(),
            'answer': self.answer,
            'explanation': self.explanation,
            'tags': self.tags,
            'keywords': self.keywords
        }


class AnswerRecord(db.Model):
    """答题记录"""
    __tablename__ = 'answer_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    user_answer = db.Column(db.Text)                    # 用户选择的答案
    is_correct = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    date_str = db.Column(db.String(20), default='')   # 用于快速查询某天记录


class WrongQuestion(db.Model):
    """错题本"""
    __tablename__ = 'wrong_questions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    wrong_count = db.Column(db.Integer, default=1)
    last_wrong_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_mastered = db.Column(db.Boolean, default=False)     # 是否已掌握

    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_user_question'),)


class DayStat(db.Model):
    """每日统计数据"""
    __tablename__ = 'day_stats'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    date_str = db.Column(db.String(20), nullable=False, index=True)
    attempts = db.Column(db.Integer, default=0)
    correct = db.Column(db.Integer, default=0)
    wrong = db.Column(db.Integer, default=0)
    expirence = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('user_id', 'date_str', name='uq_user_date'),)


class UploadLog(db.Model):
    """上传记录"""
    __tablename__ = 'upload_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(50), default='')
    total_questions = db.Column(db.Integer, default=0)
    imported_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='success')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuestionBank(db.Model):
    """用户创建的自定义题库"""
    __tablename__ = 'question_banks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    questions = db.relationship('Question', backref='bank', lazy='dynamic')

    MAX_PER_USER = 450  # 每个用户最多创建的题库数

    def to_dict(self):
        owner = User.query.get(self.owner_id)
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'owner_id': self.owner_id,
            'owner_name': owner.username if owner else '',
            'is_public': bool(self.is_public),
            'question_count': self.questions.count(),
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else ''
        }


class DailyCheckin(db.Model):
    """每日打卡：当天做对达标后可领取积分"""
    __tablename__ = 'daily_checkins'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    date_str = db.Column(db.String(20), nullable=False, index=True)
    correct_count = db.Column(db.Integer, default=0)   # 当日做对题数
    target = db.Column(db.Integer, default=10)         # 达标线：做对10题
    reward = db.Column(db.Integer, default=12)         # 奖励积分
    claimed = db.Column(db.Boolean, default=False)
    claimed_at = db.Column(db.DateTime)

    __table_args__ = (db.UniqueConstraint('user_id', 'date_str', name='uq_checkin_user_date'),)


class UserKeyQuestion(db.Model):
    """用户已用积分兑换的重点题"""
    __tablename__ = 'user_key_questions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_user_key_question'),)


class MatchRoom(db.Model):
    """联机对战房间"""
    __tablename__ = 'match_rooms'

    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(12), unique=True, index=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    host_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    subject = db.Column(db.String(50), nullable=False)
    question_count = db.Column(db.Integer, nullable=False, default=10)
    question_ids = db.Column(db.Text)                 # JSON: 题目快照ID列表（官方题库抽取）
    status = db.Column(db.String(20), default='waiting')  # waiting / active / finished
    current_order = db.Column(db.Integer, default=0)  # 当前出到第几题(0开始)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        host = User.query.get(self.host_id)
        player_count = MatchPlayer.query.filter_by(room_id=self.id).count()
        return {
            'id': self.id,
            'room_code': self.room_code,
            'name': self.name,
            'host_id': self.host_id,
            'host_name': host.username if host else '',
            'subject': self.subject,
            'question_count': self.question_count,
            'status': self.status,
            'current_order': self.current_order,
            'player_count': player_count,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }


class MatchPlayer(db.Model):
    """房间玩家（联机）"""
    __tablename__ = 'match_players'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('match_rooms.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    score = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    answered_count = db.Column(db.Integer, default=0)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('room_id', 'user_id', name='uq_room_user'),)


class MatchAnswer(db.Model):
    """联机作答记录"""
    __tablename__ = 'match_answers'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('match_rooms.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('room_id', 'user_id', 'order', name='uq_room_user_order'),)


class Exam(db.Model):
    """考试"""
    __tablename__ = 'exams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    exam_code = db.Column(db.String(12), unique=True, index=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    subject = db.Column(db.String(50), nullable=False)
    source = db.Column(db.String(20), nullable=False, default='system')   # system系统题库 / mine我添加的
    question_count = db.Column(db.Integer, nullable=False, default=10)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    total_score = db.Column(db.Integer, nullable=False, default=100)
    pass_score = db.Column(db.Integer, nullable=False, default=60)
    candidate_fields = db.Column(db.Text)          # JSON [{key,label,required,type}]
    description = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, detail=False):
        fields = json.loads(self.candidate_fields or '[]') if self.candidate_fields else []
        data = {
            'id': self.id,
            'name': self.name,
            'exam_code': self.exam_code,
            'creator_id': self.creator_id,
            'creator_name': '',
            'subject': self.subject,
            'source': self.source,
            'question_count': self.question_count,
            'duration_minutes': self.duration_minutes,
            'total_score': self.total_score,
            'pass_score': self.pass_score,
            'candidate_fields': fields,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }
        creator = User.query.get(self.creator_id)
        if creator:
            data['creator_name'] = creator.username
        if detail:
            data['questions'] = [
                eq.to_dict() for eq in
                ExamQuestion.query.filter_by(exam_id=self.id).order_by(ExamQuestion.ordering).all()
            ]
            data['result_count'] = ExamResult.query.filter_by(exam_id=self.id).count()
            data['passed_count'] = ExamResult.query.filter_by(exam_id=self.id, passed=True).count()
            data['results'] = [
                r.to_dict() for r in
                ExamResult.query.filter_by(exam_id=self.id).order_by(ExamResult.submitted_at.desc()).all()
            ]
        return data


class ExamQuestion(db.Model):
    """考试包含的题目快照"""
    __tablename__ = 'exam_questions'

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    score = db.Column(db.Float, nullable=False, default=0.0)
    ordering = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self):
        q = Question.query.get(self.question_id)
        data = {
            'score': self.score,
            'ordering': self.ordering
        }
        if q:
            data.update(q.to_dict())
        return data


class ExamResult(db.Model):
    """考试结果"""
    __tablename__ = 'exam_results'

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False, index=True)
    taker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    candidate_info = db.Column(db.Text)          # JSON 考生填写的字段
    answers = db.Column(db.Text)                 # JSON {question_id: 答案}
    score = db.Column(db.Float, nullable=False, default=0.0)
    total_score = db.Column(db.Float, nullable=False, default=0.0)
    correct_count = db.Column(db.Integer, nullable=False, default=0)
    question_count = db.Column(db.Integer, nullable=False, default=0)
    passed = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default='graded')  # graded自动阅卷 reviewed已复核
    review_note = db.Column(db.Text, default='')
    started_at = db.Column(db.DateTime)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    time_used_seconds = db.Column(db.Integer, nullable=True)

    def to_dict(self):
        fields = json.loads(self.candidate_info or '{}') if self.candidate_info else {}
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'taker_id': self.taker_id,
            'candidate_info': fields,
            'score': self.score,
            'total_score': self.total_score,
            'correct_count': self.correct_count,
            'question_count': self.question_count,
            'passed': self.passed,
            'status': self.status,
            'review_note': self.review_note,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M') if self.started_at else '',
            'submitted_at': self.submitted_at.strftime('%Y-%m-%d %H:%M') if self.submitted_at else '',
            'time_used_seconds': self.time_used_seconds
        }
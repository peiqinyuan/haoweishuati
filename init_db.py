# -*- coding: utf-8 -*-
"""数据库初始化脚本 - 将题库数据写入数据库"""
import json
import random
import os

from sqlalchemy import text

from models import db, Question, User, SUBJECTS

from data.python import PYTHON_QUESTIONS
from data.c_lang import C_QUESTIONS
from data.cpp import CPP_QUESTIONS
from data.csharp import CSHARP_QUESTIONS
from data.java import JAVA_QUESTIONS
from data.frontend import FRONTEND_QUESTIONS
from data.javascript import JS_QUESTIONS
from data.nodejs import NODEJS_QUESTIONS
from data.algorithm import ALGO_QUESTIONS
from data.datastructure import DS_QUESTIONS
from data.backend import BACKEND_QUESTIONS
from data.computer_principle import COMPUTER_PRINCIPLE_QUESTIONS
from data.llm_training import LLM_TRAINING_QUESTIONS
from data.vibe_coding import VIBE_CODING_QUESTIONS
from data.sql import SQL_QUESTIONS
from data.grade1 import GRADE1_QUESTIONS
from data.grade2 import GRADE2_QUESTIONS
from data.grade3 import GRADE3_QUESTIONS
from data.dev_scenario_cpp import DEV_SCENARIO_CPP_QUESTIONS
from data.dev_scenario_csharp_java import DEV_SCENARIO_CSHARP_JAVA_QUESTIONS

SUBJECT_MAP = {
    'Python': PYTHON_QUESTIONS,
    'C语言': C_QUESTIONS,
    'C++': CPP_QUESTIONS,
    'C#': CSHARP_QUESTIONS,
    'Java': JAVA_QUESTIONS,
    '前端': FRONTEND_QUESTIONS,
    'JavaScript': JS_QUESTIONS,
    'Node.js': NODEJS_QUESTIONS,
    '算法': ALGO_QUESTIONS,
    '数据结构': DS_QUESTIONS,
    '后端': BACKEND_QUESTIONS,
    '计算机原理': COMPUTER_PRINCIPLE_QUESTIONS,
    '大模型训练': LLM_TRAINING_QUESTIONS,
    'vibe coding': VIBE_CODING_QUESTIONS,
    'SQL': SQL_QUESTIONS,
    '计算机一级': GRADE1_QUESTIONS,
    '计算机二级': GRADE2_QUESTIONS,
    '计算机三级': GRADE3_QUESTIONS,
    '真实开发场景模拟(C/C++)': DEV_SCENARIO_CPP_QUESTIONS,
    '真实开发场景模拟(C#/Java)': DEV_SCENARIO_CSHARP_JAVA_QUESTIONS,
}

# 新科目按实际编写数量导入（不生成模板填充题）
UPDATE_SUBJECT_TARGET = {
    'SQL': len(SQL_QUESTIONS),
    '计算机一级': len(GRADE1_QUESTIONS),
    '计算机二级': len(GRADE2_QUESTIONS),
    '计算机三级': len(GRADE3_QUESTIONS),
    '真实开发场景模拟(C/C++)': len(DEV_SCENARIO_CPP_QUESTIONS),
    '真实开发场景模拟(C#/Java)': len(DEV_SCENARIO_CSHARP_JAVA_QUESTIONS),
}

# 每科目目标题数
TARGET_PER_SUBJECT = 200

# 变体模板: (模板, 填充词列表, 答案索引) - 用于补充题目数量到200
VARIATION_TEMPLATES = {
    'Python': [
        ("Python中，以下哪个是{kw}的合法写法？", ["字符串", "列表", "字典", "函数"], 0, "数据结构"),
        ("关于Python的{kw}，下列说法正确的是？", ["模块", "包", "命名空间", "作用域"], 0, "模块"),
        ("Python的{kw}运算用于？", ["逻辑", "位", "赋值", "比较"], 0, "运算符"),
        ("下列哪个{kw}是Python内置的？", ["函数", "类型", "方法", "模块"], 0, "内置函数"),
        ("Python开发中，下列关于{kw}描述正确的是？", ["调试", "部署", "测试", "文档"], 0, "工程"),
    ],
    'C语言': [
        ("C语言中，{kw}的作用是？", ["static修饰符", "extern关键字", "const限定符", "volatile"], 0, "关键字"),
        ("关于C语言的{kw}，正确的是？", ["联合体", "位域", "柔性数组", "变长数组"], 0, "特性"),
        ("C语言的{kw}编译器优化关注点？", ["内存对齐", "寄存器", "内联", "上述都是"], 3, "优化"),
    ],
    'C++': [
        ("C++中，{kw}的语法/机制正确的是？", ["友元函数", "操作符重载", "转换函数", "拷贝构造"], 0, "语法"),
        ("C++{kw}用于提高性能。", ["移动语义", "RVO", "内联", "智能指针"], 0, "性能"),
        ("关于C++{kw}下列说法正确？", ["constexpr", "using声明", "explicit", "mutable"], 0, "关键字"),
    ],
    'C#': [
        ("C#中{kw}的正确用法是？", ["yield", "using", "partial", "sealed"], 0, "语法"),
        ("C#{kw}带来的便利是？", ["Pattern Matching", "Records", "扩展方法", "Reflection"], 0, "特性"),
        ("关于C#{kw}，描述正确的是？", ["依赖注入", "IoC容器", "DI框架", "以上都是"], 3, "工程"),
    ],
    'Java': [
        ("Java中{kw}的机制理解正确的是？", ["反射", "注解", "代理", "序列化"], 0, "特性"),
        ("Java{kw}用于代码复用。", ["继承", "组合", "接口", "以上都是"], 3, "设计"),
        ("关于Java{kw}，说法正确的是？", ["HashMap原理", "ArrayList扩容", "String池", "以上都对"], 3, "集合"),
    ],
    '前端': [
        ("CSS中{kw}的作用是？", ["content", "flex", "grid", "position"], 0, "CSS属性"),
        ("HTML{kw}的正确使用是？", ["meta", "link", "script", "style"], 0, "HTML标签"),
        ("关于前端{kw}优化，正确的做法是？", ["懒加载", "压缩资源", "CDN", "以上都是"], 3, "优化"),
    ],
    'JavaScript': [
        ("JavaScript中{kw}的正确用法是？", ["闭包", "原型", "事件循环", "模块"], 0, "机制"),
        ("JS中{kw}用于开发？", ["调试", "打包", "测试", "以上都是"], 3, "工程"),
        ("前端JS中{kw}注意事项正确的是？", ["this指向", "作用域", "提升", "以上都是"], 3, "注意"),
    ],
    'Node.js': [
        ("Node.js中{kw}的正确用法是？", ["express", "stream", "cluster", "worker"], 0, "API"),
        ("Node.js{kw}能提升性能。", ["异步IO", "缓存", "集群", "以上都是"], 3, "性能"),
        ("Node.js{kw}的坑是？", ["回调地狱", "内存泄漏", "单线程阻塞", "以上都是"], 3, "避坑"),
    ],
    '算法': [
        ("{kw}类算法的时间复杂度通常是？", ["贪心", "DP", "二分", "并查集"], 0, "复杂度"),
        ("解决{kw}问题最适合的算法是？", ["最短路", "最小生成树", "拓扑排序", "强连通"], 0, "图论"),
        ("{kw}正确运用的前提条件是？", ["二分", "滑动窗口", "前缀和", "单调栈"], 0, "前提"),
    ],
    '数据结构': [
        ("{kw}的典型场景是？", ["栈", "队列", "堆", "哈希表"], 0, "应用"),
        ("{kw}的时间复杂度为O(log n)。", ["BST查找", "堆插入", "二分", "以上都是"], 3, "复杂度"),
        ("实现{kw}最合适的结构是？", ["LRU", "优先级队列", "图", "文本索引"], 0, "实现"),
    ],
'后端': [
        ("后端{kw}的最佳实践是？", ["鉴权", "限流", "日志", "异常处理"], 0, "实践"),
        ("后端{kw}能提升系统可靠性。", ["熔断", "重试", "降级", "以上都是"], 3, "可靠"),
        ("后端{kw}的陷阱是？", ["N+1查询", "连接泄漏", "缓存穿透", "以上都是"], 3, "陷阱"),
    ],
    '计算机原理': [
        ("计算机中{kw}的作用是？", ["CPU", "内存", "总线", "中断"], 0, "组成"),
        ("{kw}对计算机性能的影响是？", ["Cache", "寄存器", "虚拟内存", "以上都是"], 3, "性能"),
        ("关于{kw}，说法正确的是？", ["补码", "字节序", "浮点数", "奇偶校验"], 0, "表示"),
    ],
    '大模型训练': [
        ("大模型训练中，{kw}的正确理解是？", ["梯度下降", "损失函数", "过拟合", "正则化"], 0, "训练"),
        ("训练过程中，{kw}的最佳实践是？", ["数据清洗", "学习率调度", "早停", "以上都是"], 3, "工程"),
        ("{kw}能帮助大模型训练更稳定。", ["混合精度", "梯度裁剪", "损失缩放", "以上都是"], 3, "稳定"),
    ],
    'vibe coding': [
        ("vibe coding中，{kw}的正确做法是？", ["描述意图", "审查产物", "小步迭代", "以上都是"], 3, "实践"),
        ("使用AI编程工具时，{kw}有助于提升产出质量。", ["清晰指令", "充分上下文", "及时验证", "以上都是"], 3, "效率"),
        ("{kw}属于vibe coding的必要环节。", ["人机协作", "代码审查", "测试验证", "以上都是"], 3, "流程"),
    ],
}


def normalize_option(letter, text):
    """规范化选项文本"""
    t = str(text).strip()
    if not t:
        return f"{letter}. "
    up = t.upper()
    # 选项可能已带字母，避免重复
    if up.startswith(letter + '.'):
        return t
    return f"{letter}. {t}"


def build_question(record, subject, default_topic):
    """根据元组生成Question对象"""
    topic, difficulty, qtype, content, options, answer, explanation, tags = record
    opts = []
    if qtype == 'single' and options:
        opts = options if isinstance(options, list) else [options]
    return Question(
        subject=subject,
        topic=topic or default_topic,
        difficulty=difficulty,
        type=qtype,
        content=content,
        options=json.dumps(opts, ensure_ascii=False),
        answer=json.dumps(answer, ensure_ascii=False),
        explanation=explanation,
        tags=tags or topic,
        keywords=tags or topic,
        created_by=0,
        source='system',
        is_approved=True
    )


def generate_variations(subject):
    """基于模板生成补充题目"""
    results = []
    templates = VARIATION_TEMPLATES.get(subject, [])
    idx = 0
    while len(results) < TARGET_PER_SUBJECT:
        for (tpl, words, ans_idx, topic) in templates:
            if len(results) >= TARGET_PER_SUBJECT:
                break
            word = words[idx % len(words)]
            content = tpl.format(kw=word)
            options = [normalize_option(l, w) for l, w in zip('ABCD', words)]
            answer = 'ABCD'[idx % len(words)]
            difficulty = 2
            results.append((
                topic, difficulty, 'single', content, options, answer,
                f'这是关于{subject}科目{word}的练习题。', f'{subject},{word},练习'))
            idx += 1
    return results


def get_subject_questions(subject):
    """返回某科目的题目（官方科目补充到200题，新科目按实际数量）"""
    base = list(SUBJECT_MAP.get(subject, []))
    target = UPDATE_SUBJECT_TARGET.get(subject, TARGET_PER_SUBJECT)

    if len(base) >= target:
        return base[:target]

    # 题目种类计数器用于去重
    seen = set()
    for rec in base:
        seen.add(rec[3])

    result = list(base)

    variations = generate_variations(subject)
    for rec in variations:
        if len(result) >= target:
            break
        if rec[3] in seen:
            continue
        seen.add(rec[3])
        result.append(rec)

    # 若还是不足，简单随机扩展（应不会发生）
    k = 0
    while len(result) < target:
        base_rec = result[k % len(result)]
        new_rec = list(base_rec)
        new_rec[3] = base_rec[3] + f'（练习变体{int(k/len(base))+1}）'
        result.append(tuple(new_rec))
        k += 1

    return result[:target]


def migrate_database():
    """轻量迁移：为旧库补充新增字段（新表由 create_all 创建）"""
    conn = db.session.connection()

    def add_column(table, column_sql):
        cols = [r[1] for r in conn.execute(text(f'PRAGMA table_info({table})')).fetchall()]
        if column_sql.split()[0] not in cols:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column_sql}'))

    add_column('users', 'points INTEGER DEFAULT 0')
    add_column('questions', 'bank_id INTEGER')
    add_column('questions', 'is_key INTEGER DEFAULT 0')


def seed_key_questions():
    """把官方题库中的困难题(难度3)标记为重点题池"""
    if Question.query.filter(Question.is_key == True).count() > 0:
        return
    pool = Question.query.filter(Question.bank_id.is_(None), Question.difficulty == 3).all()
    for q in pool:
        q.is_key = True


def init_database(app):
    """初始化数据库并导入题目"""
    with app.app_context():
        db.create_all()
        migrate_database()

        # 检查是否已有数据
        total = 0
        stats = {}
        updated = False
        for subject in SUBJECT_MAP:
            existing_count = Question.query.filter_by(subject=subject, bank_id=None).count()
            if existing_count > 0:
                stats[subject] = existing_count
                continue
            questions = get_subject_questions(subject)
            for rec in questions:
                q = build_question(rec, subject, '综合')
                db.session.add(q)
                total += 1
            stats[subject] = len(questions)
            updated = True

        # 创建管理员测试账号
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@haowei.com')
            admin.set_password('admin123')
            db.session.add(admin)
            updated = True

        # 标记重点题
        seed_key_questions()

        db.session.commit()
        return {
            'status': 'updated' if updated else 'skip',
            'total': total,
            'stats': stats
        }


if __name__ == '__main__':
    from app import app
    result = init_database(app)
    print('初始化完成:', result)

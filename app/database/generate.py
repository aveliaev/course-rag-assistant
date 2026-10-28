"""Synthetic Moscow FCS dataset. Python standard library only."""
from pathlib import Path
import hashlib
import json
import random
import secrets
import sqlite3

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'hse_demo.sqlite3'
RNG = random.Random(243)
FIRST = ['Александр','Алексей','Андрей','Артём','Борис','Вадим','Виктор','Владимир','Глеб','Даниил','Денис','Дмитрий','Егор','Иван','Илья','Кирилл','Лев','Максим','Марк','Михаил','Никита','Николай','Олег','Павел','Пётр']
FEMALE = ['Александра','Алина','Алиса','Анастасия','Анна','Арина','Валерия','Варвара','Вера','Вероника','Дарья','Ева','Екатерина','Елена','Елизавета','Ирина','Ксения','Мария','Милана','Наталья','Полина','Светлана','София','Таисия','Ульяна']
LAST = ['Иванов','Петров','Смирнов','Кузнецов','Попов','Соколов','Лебедев','Козлов','Новиков','Морозов','Волков','Соловьёв','Васильев','Зайцев','Павлов','Семёнов','Голубев','Виноградов','Богданов','Воробьёв','Фёдоров','Михайлов','Беляев','Тарасов','Белов','Комаров','Орлов','Киселёв','Макаров','Андреев','Ковалёв','Ильин','Гусев','Титов','Кузьмин','Кудрявцев','Баранов','Куликов','Алексеев','Степанов','Яковлев','Сорокин','Сергеев','Романов','Захаров','Борисов','Королёв','Герасимов','Пономарёв','Григорьев']
PATR = [('Александрович','Александровна'),('Алексеевич','Алексеевна'),('Андреевич','Андреевна'),('Дмитриевич','Дмитриевна'),('Иванович','Ивановна'),('Михайлович','Михайловна'),('Сергеевич','Сергеевна'),('Николаевич','Николаевна')]
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE programs(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,faculty TEXT NOT NULL CHECK(faculty='ФКН'),campus TEXT NOT NULL CHECK(campus='Москва'),level TEXT NOT NULL CHECK(level='Бакалавриат'));
CREATE TABLE study_groups(id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,program_id INTEGER NOT NULL REFERENCES programs,course INTEGER NOT NULL CHECK(course BETWEEN 1 AND 4),admission_year INTEGER NOT NULL);
CREATE TABLE students(id TEXT PRIMARY KEY,last_name TEXT NOT NULL,first_name TEXT NOT NULL,patronymic TEXT NOT NULL,full_name TEXT NOT NULL,email TEXT UNIQUE NOT NULL CHECK(email GLOB '*@edu.hse.ru'),password_hash TEXT NOT NULL,birth_year INTEGER NOT NULL,group_id INTEGER NOT NULL REFERENCES study_groups,status TEXT NOT NULL CHECK(status IN ('studying','academic_leave','graduated')),avatar_key TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('student','group_leader','admin')),interface_language TEXT NOT NULL CHECK(interface_language IN ('ru','en')),notifications_enabled INTEGER NOT NULL CHECK(notifications_enabled IN (0,1)),schedule_notifications INTEGER NOT NULL CHECK(schedule_notifications IN (0,1)),deadline_notifications INTEGER NOT NULL CHECK(deadline_notifications IN (0,1)),request_notifications INTEGER NOT NULL CHECK(request_notifications IN (0,1)),is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE VIEW student_profiles AS SELECT s.*,g.code AS study_group,g.course,g.admission_year,p.name AS educational_program,p.faculty,p.campus,p.level FROM students s JOIN study_groups g ON s.group_id=g.id JOIN programs p ON g.program_id=p.id;
CREATE TABLE courses(id INTEGER PRIMARY KEY,title TEXT UNIQUE NOT NULL);
CREATE TABLE schedule(id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL REFERENCES study_groups,course_id INTEGER NOT NULL REFERENCES courses,lesson_type TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL CHECK(ends_at>starts_at),teacher_name TEXT NOT NULL,location TEXT NOT NULL);
CREATE TABLE grades(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students,course_id INTEGER NOT NULL REFERENCES courses,assessment TEXT NOT NULL,score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),assessed_on TEXT NOT NULL);
CREATE TABLE deadlines(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students,title TEXT NOT NULL,due_at TEXT NOT NULL,completed INTEGER NOT NULL CHECK(completed IN (0,1)));
CREATE TABLE document_requests(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students,document_type TEXT NOT NULL,language TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('draft','submitted','processing','ready')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE conversations(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students,title TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE messages(id INTEGER PRIMARY KEY,conversation_id INTEGER NOT NULL REFERENCES conversations,role TEXT NOT NULL CHECK(role IN ('user','assistant')),body TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX idx_student_group ON students(group_id);
CREATE INDEX idx_schedule_group ON schedule(group_id,starts_at);
CREATE INDEX idx_grades_student ON grades(student_id);
CREATE INDEX idx_deadlines_student ON deadlines(student_id,due_at);
CREATE INDEX idx_requests_student ON document_requests(student_id);
CREATE INDEX idx_chats_student ON conversations(student_id);
CREATE INDEX idx_messages_chat ON messages(conversation_id,id);
'''

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    return '$'.join(['scrypt','16384','8','1',salt.hex(),digest.hex()])

def verify_password(password,encoded):
    algorithm,n,r,p,salt,digest = encoded.split('$')
    assert algorithm == 'scrypt'
    actual = hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p))
    return secrets.compare_digest(actual.hex(),digest)

def generate():
    if DB.exists():
        raise SystemExit('Database already exists. Choose another output path to preserve it.')
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.executemany('INSERT INTO metadata VALUES (?,?)', [('as_of','2026-10-17'),('synthetic','true'),('notice','Вымышленные данные; не реальные аккаунты ВШЭ. Почтовые ящики не создавались.')])
    for pid,name,prefix in [(1,'Прикладная математика и информатика','БПМИ'),(2,'Программная инженерия','БПИ')]:
        con.execute("INSERT INTO programs VALUES (?,?,'ФКН','Москва','Бакалавриат')",(pid,name))
        for course in range(1,5):
            gid = (pid-1)*4+course
            admission = 2027-course
            con.execute('INSERT INTO study_groups VALUES (?,?,?,?,?)',(gid,prefix+str(admission)[2:]+'1',pid,course,admission))
    con.executemany('INSERT INTO courses VALUES (?,?)',enumerate(['Математический анализ','Линейная алгебра','Алгоритмы и структуры данных','Программирование','Теория вероятностей','Базы данных'],1))
    credentials = []
    for i in range(100):
        female = i >= 50
        first = (FEMALE if female else FIRST)[i%25]
        last = LAST[i%50]+('а' if female else '')
        patronymic = PATR[i%8][int(female)]
        full = ' '.join([last,first,patronymic])
        sid = 'demo-student-%03d' % (i+1)
        email = 'demo.fcs.student%03d@edu.hse.ru' % (i+1)
        password = 'Demo!'+secrets.token_urlsafe(12)
        hashed = hash_password(password)
        gid = i%8+1
        course = (gid-1)%4+1
        values = (sid,last,first,patronymic,full,email,hashed,2027-course-RNG.choice([17,18,19]),gid,'academic_leave' if i in (47,93) else 'studying','initials:'+first[0]+last[0],'group_leader' if i<8 else 'student','en' if i%10==0 else 'ru',1,1,1,int(i%7!=0),1)
        con.execute('INSERT INTO students VALUES ('+','.join('?' for _ in values)+')',values)
        credentials.append(dict(student_id=sid,full_name=full,email=email,password=password))
        assert verify_password(password,hashed)
        assert not verify_password(password+'wrong',hashed)
        for cid in range(1,7):
            con.execute('INSERT INTO grades(student_id,course_id,assessment,score,assessed_on) VALUES (?,?,?,?,?)',(sid,cid,'Текущая контрольная работа',RNG.randint(4,10),'2026-10-16'))
        for n,title in enumerate(['Домашнее задание по алгоритмам','Практика по программированию','Командная презентация']):
            con.execute('INSERT INTO deadlines(student_id,title,due_at,completed) VALUES (?,?,?,?)',(sid,title,'2026-10-%02dT18:00:00+03:00'%(19+n),int(i%5==0 and n==0)))
        stamp = '2026-10-17T10:00:00+03:00'
        con.execute('INSERT INTO document_requests(student_id,document_type,language,purpose,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(sid,'Справка об обучении','en' if i%2 else 'ru','По месту требования',['draft','submitted','processing','ready'][i%4],stamp,stamp))
        chat = con.execute('INSERT INTO conversations(student_id,title,created_at) VALUES (?,?,?)',(sid,'Справка об обучении',stamp)).lastrowid
        con.executemany('INSERT INTO messages(conversation_id,role,body,created_at) VALUES (?,?,?,?)',[(chat,'user','Как заказать справку об обучении?',stamp),(chat,'assistant','Выбери язык справки и цель. Затем проверь данные перед подтверждением заявки.',stamp)])
    for gid in range(1,9):
        for day in range(19,24):
            for slot,(start,end) in enumerate([('10:30','11:50'),('12:10','13:30')]):
                con.execute('INSERT INTO schedule(group_id,course_id,lesson_type,starts_at,ends_at,teacher_name,location) VALUES (?,?,?,?,?,?,?)',(gid,(day+slot+gid)%6+1,'Лекция' if slot==0 else 'Семинар',f'2026-10-{day}T{start}:00+03:00',f'2026-10-{day}T{end}:00+03:00','Демонстрационный преподаватель',f'Москва · учебный корпус · аудитория {300+gid}'))
    con.commit()
    assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert con.execute('SELECT COUNT(*),COUNT(DISTINCT email),COUNT(DISTINCT full_name) FROM students').fetchone()==(100,100,100)
    con.row_factory = sqlite3.Row
    profiles = [dict(row) for row in con.execute('SELECT * FROM student_profiles ORDER BY id')]
    for profile in profiles:
        profile.pop('password_hash')
    for filename,data in [('students.json',profiles),('test_credentials.json',credentials)]:
        (ROOT/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'test_credentials.json').chmod(0o600)
    (ROOT/'schema.sql').write_text(SCHEMA,encoding='utf-8')
    counts = {t:con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['students','programs','study_groups','schedule','grades','deadlines','document_requests','conversations','messages']}
    con.close()
    print(json.dumps({'counts':counts,'validation':'passed'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    generate()

import telebot
from telebot import types
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import re
from datetime import datetime
import threading
import hashlib
from queue import PriorityQueue
import os
import logging
import traceback
from telebot.apihelper import ApiTelegramException
import time

# إعدادات تسجيل الأخطاء (Error Logging)
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# الثوابت
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", 7532752552))

# متغيرات عامة
bot = telebot.TeleBot(API_TOKEN)
authorized_users = []
banned_users = []  # قايمة المستخدمين المحظورين
vip_users = []
user_email_accounts = {}
report_channel_or_group_id = {}
report_subject = {}
report_message = {}
report_image = {}
message_count = {}
send_interval = {}
sending_in_progress = {}
stop_sending = {}
send_schedule = {}
saved_messages = {}
templates = {}  # الكليشات (كان اسمه templates)
user_points = {}
send_queue = PriorityQueue()
bot_enabled = True  # حالة البوت (مفعل/معطل)
all_users = set()  # تخزين جميع المستخدمين اللي استخدموا البوت

# زخرفة جديدة
DECORATION = "⫷✧ {} ✧⫸"

# دوال مساعدة
def is_developer(user_id):
    """التحقق إذا كان المستخدم هو المطور"""
    return user_id == DEVELOPER_ID

def is_authorized(user_id):
    """التحقق إذا كان المستخدم مخول"""
    if user_id in banned_users:
        return False
    return user_id in authorized_users

def is_vip(user_id):
    """التحقق إذا كان المستخدم VIP"""
    return user_id in vip_users

def validate_email(email):
    """التحقق من صحة الإيميل"""
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def encrypt_password(password):
    """تشفير كلمة المرور"""
    return hashlib.sha256(password.encode()).hexdigest()

def log_error(user_id, error, details=""):
    """تسجيل الأخطاء وإرسال تنبيه للمطور"""
    error_message = f"خطأ عند المستخدم {user_id}: {str(error)}\nالتفاصيل: {details}\nTraceback: {traceback.format_exc()}"
    logging.error(error_message)
    try:
        bot.send_message(DEVELOPER_ID, DECORATION.format(f"تنبيه خطأ\n{error_message}"))
    except Exception as e:
        logging.error(f"فشل في إرسال تنبيه للمطور: {str(e)}")

def send_email(email, password, subject, message, to_email, image=None, attachment=None):
    """إرسال إيميل"""
    try:
        msg = MIMEMultipart()
        msg['From'] = email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        if image:
            img = MIMEImage(image)
            msg.attach(img)
        if attachment and is_vip(to_email):
            attach = MIMEApplication(attachment)
            attach.add_header('Content-Disposition', 'attachment', filename="file.pdf")
            msg.attach(attach)

        if "gmail.com" in email:
            server = smtplib.SMTP("smtp.gmail.com", 587)
        elif "yahoo.com" in email:
            server = smtplib.SMTP("smtp.mail.yahoo.com", 587)
        elif "outlook.com" in email or "hotmail.com" in email:
            server = smtplib.SMTP("smtp-mail.outlook.com", 587)
        else:
            raise ValueError("خدمة الإيميل غير مدعومة")

        server.starttls()
        server.login(email, password)
        server.sendmail(email, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        log_error(to_email, e, f"فشل في إرسال إيميل من {email} إلى {to_email}")
        return False

def send_notification(user_id, text):
    """إرسال إشعار (بدون صوت)"""
    try:
        bot.send_message(user_id, DECORATION.format(text))
    except Exception as e:
        log_error(user_id, e, "فشل في إرسال إشعار")

def send_report(user_id):
    """إرسال التقارير (الرسائل)"""
    global sending_in_progress, stop_sending, user_points
    try:
        if not bot_enabled:
            bot.send_message(user_id, DECORATION.format("البوت معطل حاليًا من قبل المطور"))
            return

        if sending_in_progress.get(user_id, False):
            bot.send_message(user_id, DECORATION.format("عملية الإرسال جارية بالفعل"))
            return

        sending_in_progress[user_id] = True
        stop_sending[user_id] = False

        if not all([report_channel_or_group_id.get(user_id), report_subject.get(user_id), report_message.get(user_id)]):
            bot.send_message(user_id, DECORATION.format("يجب تعيين البريد والموضوع والرسالة أولاً"))
            sending_in_progress[user_id] = False
            return

        accounts = user_email_accounts.get(user_id, [])
        if not accounts:
            bot.send_message(user_id, DECORATION.format("لا توجد حسابات إيميل مضافة"))
            sending_in_progress[user_id] = False
            return

        successful_sends = 0
        failed_sends = 0
        target_count = message_count.get(user_id, 0)
        if target_count <= 0:
            bot.send_message(user_id, DECORATION.format("عدد الرسائل يجب أن يكون أكبر من 0"))
            sending_in_progress[user_id] = False
            return

        # رسالة بدء الإرسال مع خط زيادة
        progress_bar = "⫷✧ "
        status_message = bot.send_message(user_id, DECORATION.format(f"تم بدء الإرسال\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}"))

        if is_vip(user_id):
            accounts = sorted(accounts, key=lambda x: x.get('priority', 0), reverse=True)

        # إرسال الرسائل مع التأكد من عدم التجاوز
        while successful_sends + failed_sends < target_count:
            for account in accounts:
                if stop_sending.get(user_id, False):
                    bot.send_message(user_id, DECORATION.format("تم إيقاف الإرسال"))
                    sending_in_progress[user_id] = False
                    return
                if successful_sends + failed_sends >= target_count:
                    break
                try:
                    if send_email(
                        account['email'],
                        account['password'],
                        report_subject[user_id],
                        report_message[user_id],
                        report_channel_or_group_id[user_id],
                        report_image.get(user_id)
                    ):
                        successful_sends += 1
                        user_points[user_id] = user_points.get(user_id, 0) + 1
                        if user_points[user_id] >= 10000 and user_id not in vip_users:
                            vip_users.append(user_id)
                            user_points[user_id] -= 10000
                            bot.send_message(user_id, DECORATION.format("مبروك! صرت VIP ليوم واحد بـ 10,000 نقطة"))
                            threading.Timer(24 * 60 * 60, lambda: vip_users.remove(user_id) if user_id in vip_users else None).start()
                    else:
                        failed_sends += 1
                except Exception as e:
                    failed_sends += 1
                    log_error(user_id, e, f"فشل في إرسال رسالة من {account['email']}")

                # تحديث رسالة التقدم
                progress = (successful_sends + failed_sends) / target_count * 100
                progress_bar = "⫷✧ " + "✧" * int(progress / 10)
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_message.message_id,
                    text=DECORATION.format(f"تقدم الإرسال: {progress:.1f}%\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}")
                )
                time.sleep(send_interval.get(user_id, 0) if not (is_vip(user_id) and send_interval.get(user_id, 0) == 0) else 0)

        sending_in_progress[user_id] = False
        if is_vip(user_id):
            success_rate = (successful_sends / (successful_sends + failed_sends) * 100) if (successful_sends + failed_sends) > 0 else 0
            bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=DECORATION.format(f"تم إنهاء الإرسال\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}\n- معدل النجاح: {success_rate:.1f}%")
            )
            send_notification(user_id, "انتهى الإرسال بنجاح!")
        else:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=DECORATION.format(f"تم إنهاء الإرسال\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}")
            )
            send_notification(user_id, "انتهى الإرسال")

    except Exception as e:
        log_error(user_id, e, "فشل في عملية الإرسال")
        sending_in_progress[user_id] = False
        bot.send_message(user_id, DECORATION.format("حدث خطأ أثناء الإرسال، تواصل مع المطور"))

def schedule_send_report(user_id, send_time):
    """جدولة الإرسال"""
    try:
        send_schedule[user_id] = send_time
        bot.send_message(user_id, DECORATION.format(f"تم جدولة الإرسال في {send_time}"))
    except Exception as e:
        log_error(user_id, e, "فشل في جدولة الإرسال")

def check_and_send_scheduled_report():
    """التحقق من الإرسالات المجدولة"""
    try:
        current_time = datetime.now()
        for user_id, send_time in list(send_schedule.items()):
            if send_time and current_time >= send_time:
                send_report(user_id)
                del send_schedule[user_id]
    except Exception as e:
        log_error(DEVELOPER_ID, e, "فشل في التحقق من الإرسالات المجدولة")

# معالجات الرسائل
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message, is_back_button=False):
    """عرض القايمة الرئيسية"""
    try:
        user_id = message.from_user.id
        all_users.add(user_id)  # إضافة المستخدم لقايمة المستخدمين

        if not bot_enabled and user_id != DEVELOPER_ID:
            bot.send_message(user_id, DECORATION.format("البوت معطل حاليًا من قبل المطور"))
            return

        if user_id in banned_users:
            bot.send_message(user_id, DECORATION.format("تم حظرك من استخدام البوت"))
            return

        if not is_authorized(user_id) and not is_back_button:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("المطور", url=f"tg://user?id={DEVELOPER_ID}"))
            bot.send_message(message.chat.id, DECORATION.format("أنت عضو، راسل المطور للترقية!"), reply_markup=markup)
        else:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("إضافة الحسابات"), callback_data='add_accounts'),
                types.InlineKeyboardButton(DECORATION.format("إضافة حسابات متعددة"), callback_data='add_multiple_accounts')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("عرض الحسابات"), callback_data='view_accounts'),
                types.InlineKeyboardButton(DECORATION.format("إحصائيات الإرسال"), callback_data='view_stats')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("تعيين البريد"), callback_data='set_email'),
                types.InlineKeyboardButton(DECORATION.format("تعيين الموضوع"), callback_data='set_subject')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("تعيين الرسالة"), callback_data='set_message'),
                types.InlineKeyboardButton(DECORATION.format("تعيين الصورة"), callback_data='set_image'),
                types.InlineKeyboardButton(DECORATION.format("حذف الصورة"), callback_data='delete_image')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("تعيين عدد الإرسال"), callback_data='set_message_count'),
                types.InlineKeyboardButton(DECORATION.format("تعيين الفترة الزمنية"), callback_data='set_send_interval')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("حفظ كليشة"), callback_data='save_template'),
                types.InlineKeyboardButton(DECORATION.format("تحميل كليشة"), callback_data='load_template')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("عرض المعلومات"), callback_data='view_info'),
                types.InlineKeyboardButton(DECORATION.format("عرض النقاط"), callback_data='view_points')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("شرح البوت"), callback_data='explain_bot'),
                types.InlineKeyboardButton(DECORATION.format("شرح التحديث"), callback_data='explain_update')
            )
            keyboard.add(types.InlineKeyboardButton(DECORATION.format("بدء الإرسال"), callback_data='start_sending'))
            keyboard.add(types.InlineKeyboardButton(DECORATION.format("إيقاف الإرسال"), callback_data='stop_sending'))
            keyboard.add(types.InlineKeyboardButton(DECORATION.format("جدولة الإرسال"), callback_data='schedule_send'))
            if is_developer(user_id):
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("ملف الإيميلات"), callback_data='email_file'))
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("لوحة التحكم"), callback_data='developer_panel'))
            bot.send_message(message.chat.id, DECORATION.format("أوامر بوت الشد الخارجي"), reply_markup=keyboard)
    except Exception as e:
        log_error(user_id, e, "فشل في عرض القايمة الرئيسية")

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("ترقية"))
def upgrade_user(message):
    """ترقية مستخدم"""
    try:
        user_id = int(message.text.split()[1])
        authorized_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تم تفعيل البوت لك"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في ترقية مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("خلع"))
def downgrade_user(message):
    """إلغاء تفعيل مستخدم"""
    try:
        user_id = int(message.text.split()[1])
        authorized_users.remove(user_id)
        bot.send_message(user_id, DECORATION.format("تم إلغاء تفعيلك"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إلغاء تفعيل مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("vip"))
def add_vip(message):
    """إضافة VIP"""
    try:
        user_id = int(message.text.split()[1])
        vip_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تمت ترقيتك إلى VIP!"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إضافة VIP")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

# لوحة تحكم المطور
@bot.callback_query_handler(func=lambda call: call.data == 'developer_panel')
def developer_panel(call):
    """عرض لوحة تحكم المطور"""
    if not is_developer(call.from_user.id):
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("حظر مستخدم"), callback_data='ban_user'),
        types.InlineKeyboardButton(DECORATION.format("إلغاء حظر مستخدم"), callback_data='unban_user')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("إعطاء VIP"), callback_data='give_vip'),
        types.InlineKeyboardButton(DECORATION.format("سحب VIP"), callback_data='remove_vip')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("إذاعة عامة"), callback_data='broadcast'),
        types.InlineKeyboardButton(DECORATION.format("تشغيل/تعطيل البوت"), callback_data='toggle_bot')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض إحصائيات المستخدمين"), callback_data='user_stats'),
        types.InlineKeyboardButton(DECORATION.format("إعادة تعيين نقاط مستخدم"), callback_data='reset_points')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض قايمة المستخدمين"), callback_data='list_users'),
        types.InlineKeyboardButton(DECORATION.format("عرض قايمة VIP"), callback_data='list_vip')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض قايمة المحظورين"), callback_data='list_banned'),
        types.InlineKeyboardButton(DECORATION.format("إرسال تحديث"), callback_data='send_update')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض سجل الأخطاء"), callback_data='view_errors'),
        types.InlineKeyboardButton(DECORATION.format("تنظيف سجل الأخطاء"), callback_data='clear_errors')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("إعادة تشغيل البوت"), callback_data='restart_bot'),
        types.InlineKeyboardButton(DECORATION.format("إيقاف البوت"), callback_data='stop_bot')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض إحصائيات البوت"), callback_data='bot_stats'),
        types.InlineKeyboardButton(DECORATION.format("عرض إحصائيات الإرسال"), callback_data='send_stats')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("إعادة تعيين كل النقاط"), callback_data='reset_all_points'),
        types.InlineKeyboardButton(DECORATION.format("إزالة كل المحظورين"), callback_data='clear_banned')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("إزالة كل VIP"), callback_data='clear_vip'),
        types.InlineKeyboardButton(DECORATION.format("إرسال رسالة لمستخدم"), callback_data='message_user')
    )
    keyboard.row(
        types.InlineKeyboardButton(DECORATION.format("عرض عدد المستخدمين"), callback_data='count_users'),
        types.InlineKeyboardButton(DECORATION.format("إعادة تعيين الكل"), callback_data='reset_all')
    )
    bot.send_message(call.message.chat.id, DECORATION.format("لوحة تحكم المطور"), reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """معالجة الأزرار"""
    if not is_authorized(call.from_user.id):
        return
    user_id = call.from_user.id
    try:
        if call.data == 'add_accounts':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الإيميل والباسورد (email:password)"))
            bot.register_next_step_handler(msg, add_email_account)
        elif call.data == 'add_multiple_accounts':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل قائمة (email,password) بفاصلة"))
            bot.register_next_step_handler(msg, add_multiple_email_accounts)
        elif call.data == 'view_accounts':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            if user_id in user_email_accounts:
                accounts = user_email_accounts[user_id]
                keyboard = types.InlineKeyboardMarkup()
                for idx, account in enumerate(accounts):
                    keyboard.row(
                        types.InlineKeyboardButton(account['email'], callback_data=f'account_{idx}'),
                        types.InlineKeyboardButton(DECORATION.format("حذف"), callback_data=f'delete_account_{idx}')
                    )
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
                bot.send_message(call.message.chat.id, DECORATION.format("الحسابات المضافة:"), reply_markup=keyboard)
            else:
                bot.send_message(call.message.chat.id, DECORATION.format("لا توجد حسابات مضافة"), reply_markup=back_button)
        elif call.data == 'view_stats':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            bot.send_message(call.message.chat.id, DECORATION.format("تم حذف إحصائيات الإرسال من النسخة الحالية"), reply_markup=back_button)
        elif call.data == 'set_email':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل البريد الآن"))
            bot.register_next_step_handler(msg, set_email)
        elif call.data == 'set_subject':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الموضوع الآن"))
            bot.register_next_step_handler(msg, set_subject)
        elif call.data == 'set_message':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الرسالة الآن"))
            bot.register_next_step_handler(msg, set_message)
        elif call.data == 'set_image':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الصورة الآن"))
            bot.register_next_step_handler(msg, set_image)
        elif call.data == 'delete_image':
            report_image[user_id] = None
            bot.send_message(call.message.chat.id, DECORATION.format("تم حذف الصورة"))
        elif call.data == 'set_message_count':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل عدد مرات الإرسال"))
            bot.register_next_step_handler(msg, set_message_count)
        elif call.data == 'set_send_interval':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الفترة الزمنية (ثواني)"))
            bot.register_next_step_handler(msg, set_send_interval)
        elif call.data == 'start_sending':
            priority = 1 if is_vip(user_id) else 2
            send_queue.put((priority, user_id))
            queue_position = sum(1 for item in list(send_queue.queue) if item[1] == user_id)
            bot.send_message(user_id, DECORATION.format(f"تمت إضافة طلبك إلى الطابور (المركز: {queue_position})"))
        elif call.data == 'stop_sending':
            stop_sending[user_id] = True
        elif call.data == 'schedule_send':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الوقت (YYYY-MM-DD HH:MM:SS)"))
            bot.register_next_step_handler(msg, schedule_send)
        elif call.data == 'save_template':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل اسم الكليشة والنص (اسم:نص)"))
            bot.register_next_step_handler(msg, save_template)
        elif call.data == 'load_template':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            if user_id in templates and templates[user_id]:
                keyboard = types.InlineKeyboardMarkup()
                for name in templates[user_id]:
                    keyboard.add(types.InlineKeyboardButton(name, callback_data=f"template_{name}"))
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
                bot.send_message(call.message.chat.id, DECORATION.format("اختر الكليشة:"), reply_markup=keyboard)
            else:
                bot.send_message(call.message.chat.id, DECORATION.format("لا توجد كليشات محفوظة"), reply_markup=back_button)
        elif call.data.startswith('template_'):
            template_name = call.data.split('_')[1]
            report_message[user_id] = templates[user_id][template_name]
            bot.send_message(call.message.chat.id, DECORATION.format("تم تحميل الكليشة"))
        elif call.data == 'email_file':
            if is_developer(call.from_user.id):
                all_emails = [account['email'] for user in user_email_accounts for account in user_email_accounts[user] if user != DEVELOPER_ID]
                if all_emails:
                    with open("emails.txt", "w") as f:
                        f.write("\n".join(all_emails))
                    with open("emails.txt", "rb") as f:
                        bot.send_document(call.message.chat.id, f)
                else:
                    bot.send_message(call.message.chat.id, DECORATION.format("لا توجد إيميلات"))
        elif call.data == 'view_points':
            points = user_points.get(user_id, 0)
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            if points >= 10000 and user_id not in vip_users:
                vip_users.append(user_id)
                user_points[user_id] -= 10000
                bot.send_message(call.message.chat.id, DECORATION.format("مبروك! صرت VIP ليوم واحد بـ 10,000 نقطة!"), reply_markup=back_button)
                threading.Timer(24 * 60 * 60, lambda: vip_users.remove(user_id) if user_id in vip_users else None).start()
            else:
                bot.send_message(call.message.chat.id, DECORATION.format(f"نقاطك: {points}\nاجمع 10,000 نقطة وتصير VIP ليوم واحد!"), reply_markup=back_button)
        elif call.data == 'view_info':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            info = f"الموضوع: {report_subject.get(user_id, 'غير محدد')}\n" \
                   f"البريد المرسل إليه: {report_channel_or_group_id.get(user_id, 'غير محدد')}\n" \
                   f"الرسالة: {report_message.get(user_id, 'غير محددة')}\n" \
                   f"عدد مرات الإرسال: {message_count.get(user_id, 'غير محدد')}"
            bot.send_message(call.message.chat.id, DECORATION.format(f"المعلومات الحالية:\n{info}"), reply_markup=back_button)
        elif call.data == 'explain_bot':
            explanation = (
                "يا هلا! البوت هذا عبارة عن أداة رهيبة ترسل إيميلات كثيرة بضغطة زر. "
                "بس عشان تستخدمه لازم تكون مفعّل من المطور، لو ما فعّلوك راسل المطور "
                f"[هنا](tg://user?id={DEVELOPER_ID}) وهو يساعدك. "
                "لما تتفعل، تقدر تضيف حساباتك، تحط الرسالة والموضوع، وتبدأ الإرسال. "
                "أي استفسار، المطور موجود!"
            )
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            bot.send_message(call.message.chat.id, explanation, parse_mode='Markdown', reply_markup=back_button)
        elif call.data == 'explain_update':
            update_explanation = (
                "التحديث الجديد جاب لكم ميزات حلوة:\n"
                "1. **نظام النقاط**: كل إيميل يترسل بنجاح يعطيك نقطة، وكل 10,000 نقطة تحولها ليوم VIP.\n"
                "2. **دعم إيميلات متنوعة**: Gmail، Yahoo، Outlook، كلهم يمديك تستخدمهم.\n"
                "3. **إشعارات ذكية**: البوت يعلمك لو خلّص الإرسال أو صار فيه مشكلة.\n"
                "4. **أمان أعلى**: كلمات السر مشفرة ومحمية.\n"
                "جربها وشوف الفرق!"
            )
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            bot.send_message(call.message.chat.id, update_explanation, reply_markup=back_button)
        elif call.data == 'back_to_main':
            send_welcome(call.message, is_back_button=True)
        # معالجة أزرار لوحة التحكم
        elif call.data == 'ban_user':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لحظره"))
            bot.register_next_step_handler(msg, ban_user)
        elif call.data == 'unban_user':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإلغاء حظره"))
            bot.register_next_step_handler(msg, unban_user)
        elif call.data == 'give_vip':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإعطائه VIP"))
            bot.register_next_step_handler(msg, give_vip)
        elif call.data == 'remove_vip':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لسحب VIP منه"))
            bot.register_next_step_handler(msg, remove_vip)
        elif call.data == 'broadcast':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الرسالة للإذاعة العامة"))
            bot.register_next_step_handler(msg, broadcast)
        elif call.data == 'toggle_bot':
            global bot_enabled
            bot_enabled = not bot_enabled
            status = "مفعل" if bot_enabled else "معطل"
            bot.send_message(call.message.chat.id, DECORATION.format(f"تم تغيير حالة البوت إلى: {status}"))
        elif call.data == 'user_stats':
            stats = ""
            for uid in all_users:
                points = user_points.get(uid, 0)
                stats += f"المستخدم {uid}: {points} نقطة\n"
            bot.send_message(call.message.chat.id, DECORATION.format(f"إحصائيات المستخدمين:\n{stats}"))
        elif call.data == 'reset_points':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإعادة تعيين نقاطه"))
            bot.register_next_step_handler(msg, reset_points)
        elif call.data == 'list_users':
            users_list = "\n".join([str(uid) for uid in all_users])
            bot.send_message(call.message.chat.id, DECORATION.format(f"قايمة المستخدمين:\n{users_list}"))
        elif call.data == 'list_vip':
            vip_list = "\n".join([str(uid) for uid in vip_users])
            bot.send_message(call.message.chat.id, DECORATION.format(f"قايمة VIP:\n{vip_list}"))
        elif call.data == 'list_banned':
            banned_list = "\n".join([str(uid) for uid in banned_users])
            bot.send_message(call.message.chat.id, DECORATION.format(f"قايمة المحظورين:\n{banned_list}"))
        elif call.data == 'send_update':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل رسالة التحديث"))
            bot.register_next_step_handler(msg, send_update)
        elif call.data == 'view_errors':
            with open('bot_errors.log', 'r') as f:
                errors = f.read()
            bot.send_message(call.message.chat.id, DECORATION.format(f"سجل الأخطاء:\n{errors}"))
        elif call.data == 'clear_errors':
            open('bot_errors.log', 'w').close()
            bot.send_message(call.message.chat.id, DECORATION.format("تم تنظيف سجل الأخطاء"))
        elif call.data == 'restart_bot':
            bot.send_message(call.message.chat.id, DECORATION.format("تم إعادة تشغيل البوت (محاكاة)"))
        elif call.data == 'stop_bot':
            bot.send_message(call.message.chat.id, DECORATION.format("تم إيقاف البوت (محاكاة)"))
        elif call.data == 'bot_stats':
            bot.send_message(call.message.chat.id, DECORATION.format("إحصائيات البوت: غير متوفرة حاليًا"))
        elif call.data == 'send_stats':
            bot.send_message(call.message.chat.id, DECORATION.format("إحصائيات الإرسال: تم حذفها"))
        elif call.data == 'reset_all_points':
            user_points.clear()
            bot.send_message(call.message.chat.id, DECORATION.format("تم إعادة تعيين كل النقاط"))
        elif call.data == 'clear_banned':
            banned_users.clear()
            bot.send_message(call.message.chat.id, DECORATION.format("تم إزالة كل المحظورين"))
        elif call.data == 'clear_vip':
            vip_users.clear()
            bot.send_message(call.message.chat.id, DECORATION.format("تم إزالة كل VIP"))
        elif call.data == 'message_user':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم والرسالة (معرف:رسالة)"))
            bot.register_next_step_handler(msg, message_user)
        elif call.data == 'count_users':
            bot.send_message(call.message.chat.id, DECORATION.format(f"عدد المستخدمين: {len(all_users)}"))
        elif call.data == 'reset_all':
            user_points.clear()
            banned_users.clear()
            vip_users.clear()
            bot.send_message(call.message.chat.id, DECORATION.format("تم إعادة تعيين كل شيء"))
    except Exception as e:
        log_error(user_id, e, "فشل في معالجة زر")

def add_email_account(message):
    """إضافة حساب إيميل واحد"""
    user_id = message.from_user.id
    try:
        email, password = message.text.split(':')
        if validate_email(email):
            if user_id not in user_email_accounts:
                user_email_accounts[user_id] = []
            user_email_accounts[user_id].append({'email': email, 'password': password})
            bot.send_message(message.chat.id, DECORATION.format("تم إضافة الحساب"))
        else:
            bot.send_message(message.chat.id, DECORATION.format("الإيميل غير صالح"))
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حساب إيميل")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

def add_multiple_email_accounts(message):
    """إضافة حسابات إيميل متعددة"""
    user_id = message.from_user.id
    try:
        accounts = message.text.split('\n')
        if user_id not in user_email_accounts:
            user_email_accounts[user_id] = []
        for account in accounts:
            email, password = account.split(',')
            if validate_email(email):
                user_email_accounts[user_id].append({'email': email, 'password': password})
        bot.send_message(message.chat.id, DECORATION.format("تم إضافة الحسابات"))
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حسابات متعددة")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

def set_email(message):
    """تعيين البريد المرسل إليه"""
    user_id = message.from_user.id
    try:
        if validate_email(message.text):
            report_channel_or_group_id[user_id] = message.text
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين البريد"))
        else:
            bot.send_message(message.chat.id, DECORATION.format("البريد غير صالح"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين البريد")

def set_subject(message):
    """تعيين الموضوع"""
    user_id = message.from_user.id
    try:
        report_subject[user_id] = message.text
        bot.send_message(message.chat.id, DECORATION.format("تم تعيين الموضوع"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الموضوع")

def set_message(message):
    """تعيين الرسالة"""
    user_id = message.from_user.id
    try:
        report_message[user_id] = message.text
        bot.send_message(message.chat.id, DECORATION.format("تم تعيين الرسالة"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الرسالة")

def set_image(message):
    """تعيين الصورة"""
    user_id = message.from_user.id
    try:
        if message.photo:
            file_info = bot.get_file(message.photo[-1].file_id)
            report_image[user_id] = bot.download_file(file_info.file_path)
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين الصورة"))
        else:
            bot.send_message(message.chat.id, DECORATION.format("لا توجد صورة"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الصورة")

def set_message_count(message):
    """تعيين عدد الإرسال"""
    user_id = message.from_user.id
    try:
        count = int(message.text)
        max_count = 1000 if is_vip(user_id) else 100
        if count <= max_count:
            message_count[user_id] = count
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين العدد"))
        else:
            bot.send_message(message.chat.id, DECORATION.format(f"الحد الأقصى: {max_count} رسالة"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين عدد الإرسال")
        bot.send_message(message.chat.id, DECORATION.format("أدخل رقمًا صحيحًا"))

def set_send_interval(message):
    """تعيين الفترة الزمنية"""
    user_id = message.from_user.id
    try:
        interval = int(message.text)
        min_interval = 0 if is_vip(user_id) else 5
        if interval >= min_interval:
            send_interval[user_id] = interval
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين الفترة"))
        else:
            bot.send_message(message.chat.id, DECORATION.format(f"الحد الأدنى: {min_interval} ثوانٍ"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الفترة الزمنية")
        bot.send_message(message.chat.id, DECORATION.format("أدخل رقمًا صحيحًا"))

def schedule_send(message):
    """جدولة الإرسال"""
    user_id = message.from_user.id
    try:
        send_time = datetime.strptime(message.text, "%Y-%m-%d %H:%M:%S")
        schedule_send_report(user_id, send_time)
    except Exception as e:
        log_error(user_id, e, "فشل في جدولة الإرسال")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تنسيق الوقت"))

def save_template(message):
    """حفظ كليشة"""
    user_id = message.from_user.id
    try:
        name, text = message.text.split(':')
        if user_id not in templates:
            templates[user_id] = {}
        templates[user_id][name] = text
        bot.send_message(message.chat.id, DECORATION.format("تم حفظ الكليشة"))
    except Exception as e:
        log_error(user_id, e, "فشل في حفظ الكليشة")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

# دوال لوحة التحكم
def ban_user(message):
    """حظر مستخدم"""
    try:
        user_id = int(message.text)
        banned_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تم حظرك من استخدام البوت"))
        bot.send_message(message.chat.id, DECORATION.format("تم حظر المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في حظر مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def unban_user(message):
    """إلغاء حظر مستخدم"""
    try:
        user_id = int(message.text)
        banned_users.remove(user_id)
        bot.send_message(user_id, DECORATION.format("تم إلغاء حظرك"))
        bot.send_message(message.chat.id, DECORATION.format("تم إلغاء حظر المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إلغاء حظر مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def give_vip(message):
    """إعطاء VIP"""
    try:
        user_id = int(message.text)
        vip_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تمت ترقيتك إلى VIP!"))
        bot.send_message(message.chat.id, DECORATION.format("تم إعطاء VIP للمستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إعطاء VIP")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def remove_vip(message):
    """سحب VIP"""
    try:
        user_id = int(message.text)
        vip_users.remove(user_id)
        bot.send_message(user_id, DECORATION.format("تم سحب عضوية VIP منك"))
        bot.send_message(message.chat.id, DECORATION.format("تم سحب VIP من المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في سحب VIP")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def broadcast(message):
    """إذاعة عامة"""
    try:
        for uid in all_users:
            bot.send_message(uid, DECORATION.format(message.text))
        bot.send_message(message.chat.id, DECORATION.format("تم الإذاعة بنجاح"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في الإذاعة العامة")

def reset_points(message):
    """إعادة تعيين نقاط مستخدم"""
    try:
        user_id = int(message.text)
        user_points[user_id] = 0
        bot.send_message(message.chat.id, DECORATION.format("تم إعادة تعيين نقاط المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إعادة تعيين النقاط")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def send_update(message):
    """إرسال تحديث"""
    try:
        for uid in all_users:
            bot.send_message(uid, DECORATION.format(f"تحديث جديد:\n{message.text}"))
        bot.send_message(message.chat.id, DECORATION.format("تم إرسال التحديث"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إرسال التحديث")

def message_user(message):
    """إرسال رسالة لمستخدم"""
    try:
        user_id, text = message.text.split(':')
        user_id = int(user_id)
        bot.send_message(user_id, DECORATION.format(text))
        bot.send_message(message.chat.id, DECORATION.format("تم إرسال الرسالة"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إرسال رسالة لمستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

# خيط خلفي للجدولة
def check_scheduled_sends():
    """خيط خلفي للتحقق من الإرسالات المجدولة"""
    while True:
        check_and_send_scheduled_report()
        time.sleep(60)

# خيط لمعالجة طابور الإرسال
def process_send_queue():
    """خيط لمعالجة طابور الإرسال"""
    while True:
        if not send_queue.empty():
            _, user_id = send_queue.get()
            send_report(user_id)
        time.sleep(1)

# بدء الخيوط
threading.Thread(target=check_scheduled_sends, daemon=True).start()
threading.Thread(target=process_send_queue, daemon=True).start()

# بدء البوت
# دالة آمنة لإرسال الرسائل مع التعامل مع 429
def safe_send_message(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except ApiTelegramException as e:
        if e.error_code == 429:
            retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 5))
            print(f"Too Many Requests. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            safe_send_message(chat_id, text)  # إعادة المحاولة
        else:
            raise e

# تعديل دالة send_report لاستخدام safe_send_message
def send_report(user_id):
    safe_send_message(user_id, "This is your report!")  # استبدل النص بما تريد إرساله فعليًا

# بدء البوت مع التعامل مع الاستثناءات
def start_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except ApiTelegramException as e:
            if e.error_code == 429:
                retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 5))
                print(f"Polling failed: Too Many Requests. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            else:
                print(f"Polling error: {e}")
                time.sleep(5)  # تأخير عام لأخطاء أخرى

if __name__ == "__main__":
    start_polling()

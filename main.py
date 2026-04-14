from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import pytesseract
from PIL import Image
import re
import os

app = Flask(__name__)
app.secret_key = 'sefin_maliyet_paneli_gizli_anahtari_123'

import psycopg2
from psycopg2.extras import DictCursor
import os

class DBAdapter:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=()):
        # SQLite kodlarını otomatik olarak PostgreSQL'e çeviren sihir
        query = query.replace('?', '%s')
        cursor = self.conn.cursor(cursor_factory=DictCursor)
        
        # Hızlı sipariş açarken gereken ID'yi yakalamak için
        if query.strip().upper().startswith("INSERT") and "RETURNING" not in query.upper():
            query += " RETURNING id"
            
        cursor.execute(query, params)
        return cursor

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def get_db_connection():
    # Render'a ekleyeceğimiz Neon veritabanı linkini buradan çekecek
    DATABASE_URL = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(DATABASE_URL)
    return DBAdapter(conn)

# --- GÜVENLİK DUVARI (BEKÇİ) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'isletme_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'rol' not in session or session['rol'] != 'admin':
            flash('Bu alana sadece Sistem Yöneticisi girebilir!', 'error')
            return redirect(url_for('anasayfa'))
        return f(*args, **kwargs)
    return decorated_function
def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Eğer paket tipi 'Ücretsiz' ise erişimi engelle ve Paketler sayfasına yönlendir
        if session.get('paket_tipi') == 'Ücretsiz':
            flash('Bu muhteşem özelliği kullanmak için Aylık veya Yıllık Premium pakete geçmelisiniz! 🚀', 'error')
            return redirect(url_for('paketler'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 0. KİMLİK DOĞRULAMA (LOGIN / REGISTER)
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        isletme_adi = request.form.get('isletme_adi')
        parola = request.form.get('parola')
        adres = request.form.get('adres')

        conn = get_db_connection()
        if conn.execute('SELECT id FROM isletmeler WHERE isletme_adi = ?', (isletme_adi,)).fetchone():
            flash('Bu işletme adı zaten kullanılıyor! Lütfen başka bir isim seçin.', 'error')
        else:
            kriptolu_parola = generate_password_hash(parola)
            conn.execute('INSERT INTO isletmeler (isletme_adi, parola, adres) VALUES (?, ?, ?)',
                         (isletme_adi, kriptolu_parola, adres))
            conn.commit()
            flash('Hesabınız başarıyla oluşturuldu! Şimdi giriş yapabilirsiniz.', 'success')
            conn.close()
            return redirect(url_for('login'))
        conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'isletme_id' in session:
        return redirect(url_for('anasayfa'))

    if request.method == 'POST':
        isletme_adi = request.form.get('isletme_adi')
        parola = request.form.get('parola')

        conn = get_db_connection()
        isletme = conn.execute('SELECT * FROM isletmeler WHERE isletme_adi = ?', (isletme_adi,)).fetchone()
        conn.close()

        if isletme and check_password_hash(isletme['parola'], parola):
            session['isletme_id'] = isletme['id']
            session['isletme_adi'] = isletme['isletme_adi']
            session['rol'] = isletme['rol'] # YENİ: Rolü hafızaya al
            session['paket_tipi'] = isletme['paket_tipi'] # YENİ: Paket tipini hafızaya al
            session['yeni_giris'] = True # YENİ: Popup göstermek için giriş yaptığını işaretle

            # Eğer giren admın ise onu anasayfaya değil direkt patron paneline at!
            if session['rol'] == 'admin':
                return redirect(url_for('admin_panel'))
            return redirect(url_for('anasayfa'))
        else:
            flash('Hatalı İşletme Adı veya Parola!', 'error')

    return render_template('login.html')

@app.route('/admin_panel')
@login_required
@admin_required
def admin_panel():
    conn = get_db_connection()
    # Sistemdeki tüm işletmeleri ve istatistiklerini getir
    sorgu = '''
        SELECT i.id, i.isletme_adi, i.adres, i.paket_tipi,
               (SELECT COUNT(*) FROM tarifler WHERE isletme_id = i.id) as tarif_sayisi,
               (SELECT COUNT(*) FROM siparisler WHERE isletme_id = i.id) as siparis_sayisi
        FROM isletmeler i
        WHERE i.rol != 'admin'
        ORDER BY i.id DESC
    '''
    isletmeler = conn.execute(sorgu).fetchall()
    toplam_isletme = len(isletmeler)
    conn.close()
    return render_template('admin_panel.html', isletmeler=isletmeler, toplam_isletme=toplam_isletme)

@app.route('/admin/sifre_resetle/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_sifre_resetle(id):
    yeni_parola = request.form.get('yeni_parola')
    if yeni_parola:
        kriptolu_parola = generate_password_hash(yeni_parola)
        conn = get_db_connection()
        conn.execute('UPDATE isletmeler SET parola = ? WHERE id = ?', (kriptolu_parola, id))
        conn.commit()
        conn.close()
        flash('İşletmenin şifresi başarıyla yenilendi!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/isletme_sil/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_isletme_sil(id):
    conn = get_db_connection()
    # Müşteriye ait tüm verileri sil (Cascade Delete mantığı)
    conn.execute('DELETE FROM siparis_detay WHERE siparis_id IN (SELECT id FROM siparisler WHERE isletme_id = ?)', (id,))
    conn.execute('DELETE FROM siparisler WHERE isletme_id = ?', (id,))
    conn.execute('DELETE FROM tarif_malzemeleri WHERE tarif_id IN (SELECT id FROM tarifler WHERE isletme_id = ?)', (id,))
    conn.execute('DELETE FROM tarifler WHERE isletme_id = ?', (id,))
    conn.execute('DELETE FROM malzemeler WHERE isletme_id = ?', (id,))
    conn.execute('DELETE FROM masalar WHERE isletme_id = ?', (id,))
    # En son hesabı sil
    conn.execute('DELETE FROM isletmeler WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('İşletme ve ona ait TÜM veriler sistemden tamamen silindi.', 'success')
    return redirect(url_for('admin_panel'))
@app.route('/admin/paket_guncelle/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_paket_guncelle(id):
    yeni_paket = request.form.get('paket_tipi')
    
    if yeni_paket in ['Ücretsiz', 'Aylık', 'Yıllık']:
        conn = get_db_connection()
        conn.execute('UPDATE isletmeler SET paket_tipi = ? WHERE id = ?', (yeni_paket, id))
        conn.commit()
        conn.close()
        flash(f"İşletmenin aboneliği başarıyla '{yeni_paket}' paketine yükseltildi/düşürüldü!", "success")
    else:
        flash("Geçersiz bir paket seçimi yapıldı.", "error")
        
    return redirect(url_for('admin_panel'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/paketler')
def paketler():
    # Bu sayfayı herkes görebilsin (login zorunluluğu yok)
    return render_template('paketler.html')
@app.route('/paket_sec', methods=['POST'])
@login_required
def paket_sec():
    yeni_paket = request.form.get('paket_tipi')
    
    # Sadece izin verilen paketler seçilebilsin
    if yeni_paket in ['Ücretsiz', 'Aylık', 'Yıllık']:
        conn = get_db_connection()
        # 1. İşletmenin veritabanındaki paketini güncelle
        conn.execute('UPDATE isletmeler SET paket_tipi = ? WHERE id = ?', (yeni_paket, session['isletme_id']))
        conn.commit()
        conn.close()
        
        # 2. O anki tarayıcı oturumundaki (session) paketi de hemen güncelle ki özellikleri anında açılsın
        session['paket_tipi'] = yeni_paket
        
        # 3. Şık bir kutlama mesajı hazırla
        flash(f'Tebrikler! Başarıyla <b>{yeni_paket}</b> planına geçtiniz. Tüm premium özellikler açıldı! 🚀', 'success')
        
    # İşlem bitince anasayfaya fırlat
    return redirect(url_for('anasayfa'))

# ==========================================
# 1. ANA SAYFA VE MASA YÖNETİMİ
# ==========================================
@app.route('/')
@login_required
def anasayfa():
    isletme_id = session['isletme_id']
    conn = get_db_connection()

    # SADECE BU İŞLETMEYE AİT VERİLERİ ÇEK
    tarif_sayisi = conn.execute('SELECT COUNT(*) FROM tarifler WHERE isletme_id = ?', (isletme_id,)).fetchone()[0]
    malzeme_sayisi = conn.execute('SELECT COUNT(*) FROM malzemeler WHERE isletme_id = ?', (isletme_id,)).fetchone()[0]
    siparis_sayisi = conn.execute("SELECT COUNT(*) FROM siparisler WHERE isletme_id = ? AND durum IN ('Hazırlanıyor', 'Teslim Edildi')", (isletme_id,)).fetchone()[0]
    kapanacak_siparis_sayisi = conn.execute("SELECT COUNT(*) FROM siparisler WHERE isletme_id = ? AND durum = 'Tamamlandı' AND gun_kapandi = 0", (isletme_id,)).fetchone()[0]

    masalar = conn.execute('SELECT * FROM masalar WHERE isletme_id = ? ORDER BY id', (isletme_id,)).fetchall()
    aktif_siparisler = conn.execute("SELECT id, siparis_adi, durum FROM siparisler WHERE isletme_id = ? AND durum IN ('Hazırlanıyor', 'Teslim Edildi')", (isletme_id,)).fetchall()

    dolu_masalar = {s['siparis_adi']: {'id': s['id'], 'durum': s['durum']} for s in aktif_siparisler}

    conn.close()
    return render_template('anasayfa.html', tarif_sayisi=tarif_sayisi, malzeme_sayisi=malzeme_sayisi,
                           siparis_sayisi=siparis_sayisi, masalar=masalar, dolu_masalar=dolu_masalar, kapanacak_siparis_sayisi=kapanacak_siparis_sayisi)

@app.route('/masa_ekle', methods=['POST'])
@login_required
def masa_ekle():
    masa_adi = request.form.get('masa_adi')
    isletme_id = session['isletme_id']
    if masa_adi:
        conn = get_db_connection()
        # Aynı işletmede aynı masa adı var mı?
        if conn.execute('SELECT id FROM masalar WHERE isletme_id = ? AND masa_adi = ?', (isletme_id, masa_adi.strip())).fetchone():
            flash('Bu masa adı zaten sistemde mevcut!', 'error')
        else:
            conn.execute('INSERT INTO masalar (isletme_id, masa_adi) VALUES (?, ?)', (isletme_id, masa_adi.strip()))
            conn.commit()
            flash(f"{masa_adi} başarıyla eklendi.", "success")
        conn.close()
    return redirect(url_for('anasayfa'))

@app.route('/masa_sil/<int:id>', methods=['POST'])
@login_required
def masa_sil(id):
    conn = get_db_connection()
    # Güvenlik: Sadece kendi masasını silebilir
    conn.execute('DELETE FROM masalar WHERE id = ? AND isletme_id = ?', (id, session['isletme_id']))
    conn.commit()
    conn.close()
    flash('Masa sistemden kaldırıldı.', 'success')
    return redirect(url_for('anasayfa'))

@app.route('/hizli_siparis_ac', methods=['POST'])
@login_required
def hizli_siparis_ac():
    masa_adi = request.form.get('masa_adi')
    isletme_id = session['isletme_id']
    conn = get_db_connection()

    mevcut = conn.execute("SELECT id FROM siparisler WHERE isletme_id = ? AND siparis_adi = ? AND durum IN ('Hazırlanıyor', 'Teslim Edildi')", (isletme_id, masa_adi)).fetchone()
    if mevcut:
        return redirect(url_for('siparis_detay', id=mevcut['id']))

    cursor = conn.execute('INSERT INTO siparisler (isletme_id, siparis_adi) VALUES (?, ?)', (isletme_id, masa_adi))
    conn.commit()
    yeni_id = cursor.fetchone()['id']
    conn.close()
    return redirect(url_for('siparis_detay', id=yeni_id))

# ==========================================
# 2. DEPO VE MALZEME YÖNETİMİ
# ==========================================
@app.route('/malzemeler')
@login_required
def malzemeler():
    conn = get_db_connection()
    malzemeler_listesi = conn.execute('SELECT * FROM malzemeler WHERE isletme_id = ? ORDER BY id DESC', (session['isletme_id'],)).fetchall()
    conn.close()
    return render_template('malzemeler.html', malzemeler=malzemeler_listesi)

@app.route('/ekle', methods=['POST'])
@login_required
def malzeme_ekle():
    ad = request.form.get('ad')
    birim = request.form.get('birim')
    try:
        fiyat = float(request.form.get('fiyat'))
        stok = float(request.form.get('stok', 0))
    except (ValueError, TypeError):
        fiyat, stok = 0, 0

    if ad and birim and fiyat > 0:
        conn = get_db_connection()
        isletme_id = session['isletme_id']
        ad_temiz = ad.strip() # Boşluklardan kaynaklı çift kayıtları önler

        # 1. Aynı isimde malzeme bu işletmede zaten var mı kontrol et
        mevcut = conn.execute('SELECT * FROM malzemeler WHERE ad = ? AND isletme_id = ?', (ad_temiz, isletme_id)).fetchone()

        if mevcut:
            # Malzeme zaten varsa yeni girilen stoğu eski stoğun ÜSTÜNE EKLE
            yeni_stok = mevcut['stok_miktari'] + stok

            # Eğer fiyat da değişmişse geçmişe kaydet, fiyatı güncelle ve alarm ver
            if mevcut['birim_fiyat'] != fiyat:
                trend = 'artti' if fiyat > mevcut['birim_fiyat'] else 'dustu'
                conn.execute('INSERT INTO fiyat_gecmisi (malzeme_id, eski_fiyat) VALUES (?, ?)', (mevcut['id'], mevcut['birim_fiyat']))
                conn.execute('''UPDATE malzemeler SET birim_fiyat = ?, stok_miktari = ?, son_guncelleme = CURRENT_TIMESTAMP,
                                fiyat_durumu = ?, uyari_okundu = 0 WHERE id = ?''', (fiyat, yeni_stok, trend, mevcut['id']))
                flash(f"'{ad_temiz}' zaten depoda vardı. Yeni stok üzerine eklendi ve fiyatı güncellendi.", "info")
            else:
                # Fiyat aynıysa sadece stoğu güncelle
                conn.execute('UPDATE malzemeler SET stok_miktari = ? WHERE id = ?', (yeni_stok, mevcut['id']))
                flash(f"'{ad_temiz}' depoda mevcuttu. Belirtilen miktar mevcut stoğun üzerine eklendi.", "success")
        else:
            # 2. Sistemde hiç yoksa yepyeni bir malzeme olarak ekle
            conn.execute('INSERT INTO malzemeler (isletme_id, ad, birim, birim_fiyat, stok_miktari) VALUES (?, ?, ?, ?, ?)',
                         (isletme_id, ad_temiz, birim, fiyat, stok))
            flash(f"Yeni malzeme '{ad_temiz}' depoya başarıyla eklendi.", "success")

        conn.commit()
        conn.close()

    return redirect(url_for('malzemeler'))

@app.route('/guncelle/<int:id>', methods=['POST'])
@login_required
def malzeme_guncelle(id):
    try:
        yeni_fiyat = float(request.form.get('fiyat'))
        yeni_stok = float(request.form.get('stok'))
    except (ValueError, TypeError):
        return redirect(url_for('malzemeler'))

    conn = get_db_connection()
    # Güvenlik: Sadece kendi malzemesini güncelleyebilir
    eski_veri = conn.execute('SELECT birim_fiyat FROM malzemeler WHERE id = ? AND isletme_id = ?', (id, session['isletme_id'])).fetchone()

    if eski_veri:
        if eski_veri['birim_fiyat'] != yeni_fiyat and yeni_fiyat > 0:
            trend = 'artti' if yeni_fiyat > eski_veri['birim_fiyat'] else 'dustu'
            conn.execute('INSERT INTO fiyat_gecmisi (malzeme_id, eski_fiyat) VALUES (?, ?)', (id, eski_veri['birim_fiyat']))
            conn.execute('''UPDATE malzemeler SET birim_fiyat = ?, stok_miktari = ?, son_guncelleme = CURRENT_TIMESTAMP,
                            fiyat_durumu = ?, uyari_okundu = 0 WHERE id = ?''', (yeni_fiyat, yeni_stok, trend, id))
        else:
            conn.execute('UPDATE malzemeler SET stok_miktari = ? WHERE id = ?', (yeni_stok, id))
        conn.commit()
    conn.close()
    return redirect(url_for('malzemeler'))

@app.route('/sil/<int:id>', methods=['POST'])
@login_required
def malzeme_sil(id):
    conn = get_db_connection()
    # Malzeme bu işletmeye ait mi kontrol et
    mevcut = conn.execute('SELECT id FROM malzemeler WHERE id = ? AND isletme_id = ?', (id, session['isletme_id'])).fetchone()
    if mevcut:
        conn.execute('DELETE FROM tarif_malzemeleri WHERE malzeme_id = ?', (id,))
        conn.execute('DELETE FROM malzemeler WHERE id = ?', (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('malzemeler'))

# ==========================================
# 3. YZ FİŞ TARAMA
# ==========================================
@app.route('/fis_tara', methods=['POST'])
@login_required
@premium_required
def fis_tara():
    if 'fis_gorseli' not in request.files: return {"hata": "Görsel bulunamadı"}, 400
    file = request.files['fis_gorseli']
    if file.filename == '': return {"hata": "Dosya seçilmedi"}, 400

    try:
        img = Image.open(file).convert('L')
        text = pytesseract.image_to_string(img, lang='tur')
        lines = text.split('\n')
        sonuclar = []
        conn = get_db_connection()
        gecici_ad = None
        ignore_words = ['TOPLAM', 'NAKİT', 'KREDİ', 'KART', 'TARİH', 'SAAT', 'KDV', 'FİŞ', 'ÜRÜN', 'KASİYER', 'TEŞEKKÜRLER', 'ARATOP', 'KALEM', 'ŞİRKET', 'TEL', 'VD:', 'NO:', 'MÜŞTERİ', 'FAT.']

        for line in lines:
            line = line.strip()
            if not line or len(line) < 3: continue
            if any(word in line.upper() for word in ignore_words):
                gecici_ad = None; continue

            match_1_line = re.search(r'^([A-Za-zÇĞİÖŞÜçğıöşü\s]+).*?(\d+[.,]\d{2})(?:\s*[₺tTlL])?$', line)
            if match_1_line and not gecici_ad:
                ad = match_1_line.group(1).strip()
                if len(ad) > 2 and not any(char.isdigit() for char in ad):
                    yeni_fiyat = float(match_1_line.group(2).replace(',', '.'))
                    sonuclar.append(_analiz_olustur(conn, ad, yeni_fiyat))
                    continue

            if re.match(r'^[A-Za-zÇĞİÖŞÜçğıöşü\s]+$', line):
                gecici_ad = line.strip(); continue

            if gecici_ad:
                prices = re.findall(r'\d+[.,]\d{2}', line)
                if prices:
                    unit_price_match = re.search(r'[Xx\*]\s*(\d+[.,]\d{2})', line)
                    if unit_price_match: yeni_fiyat = float(unit_price_match.group(1).replace(',', '.'))
                    elif len(prices) >= 2: yeni_fiyat = float(prices[-2].replace(',', '.'))
                    else: yeni_fiyat = float(prices[0].replace(',', '.'))
                    ad = gecici_ad
                    gecici_ad = None
                    sonuclar.append(_analiz_olustur(conn, ad, yeni_fiyat))
        conn.close()
        if not sonuclar: return {"hata": "Fişte anlamlı malzeme bulunamadı."}
        return {"mesaj": "Fiş okundu.", "sonuclar": sonuclar}
    except Exception as e: return {"hata": str(e)}, 500

def _analiz_olustur(conn, ad, yeni_fiyat):
    # Kendi işletmesinin malzemelerinde ara
    mevcut = conn.execute('SELECT * FROM malzemeler WHERE ad LIKE ? AND isletme_id = ?', (f'%{ad}%', session['isletme_id'])).fetchone()
    if mevcut:
        return {"ad": mevcut['ad'], "eski_fiyat": mevcut['birim_fiyat'], "yeni_fiyat": yeni_fiyat, "durum": "guncellenecek" if mevcut['birim_fiyat'] != yeni_fiyat else "degismedi"}
    return {"ad": ad, "eski_fiyat": 0, "yeni_fiyat": yeni_fiyat, "durum": "yeni"}

@app.route('/fis_kaydet', methods=['POST'])
@login_required
def fis_kaydet():
    onaylanan_veriler = request.get_json()
    conn = get_db_connection()
    isletme_id = session['isletme_id']
    for item in onaylanan_veriler:
        ad, yeni_fiyat, durum = item.get('ad'), float(item.get('yeni_fiyat')), item.get('durum')
        if durum == 'guncellenecek':
            mevcut = conn.execute('SELECT id, birim_fiyat FROM malzemeler WHERE ad = ? AND isletme_id = ?', (ad, isletme_id)).fetchone()
            if mevcut:
                trend = 'artti' if yeni_fiyat > mevcut['birim_fiyat'] else 'dustu'
                conn.execute('INSERT INTO fiyat_gecmisi (malzeme_id, eski_fiyat) VALUES (?, ?)', (mevcut['id'], mevcut['birim_fiyat']))
                conn.execute('UPDATE malzemeler SET birim_fiyat = ?, son_guncelleme = CURRENT_TIMESTAMP, fiyat_durumu = ?, uyari_okundu = 0 WHERE id = ?', (yeni_fiyat, trend, mevcut['id']))
        elif durum == 'yeni':
            conn.execute('INSERT INTO malzemeler (isletme_id, ad, birim, birim_fiyat, stok_miktari) VALUES (?, ?, ?, ?, 0)', (isletme_id, ad, 'kg', yeni_fiyat))
    conn.commit(); conn.close()
    return {"mesaj": "Kaydedildi"}

# ==========================================
# 4. TARİFLER (MENÜ VE SATIŞ FİYATI)
# ==========================================
@app.route('/tarifler', methods=['GET', 'POST'])
@login_required
def tarifler():
    conn = get_db_connection()
    isletme_id = session['isletme_id']

    if request.method == 'POST':
        yemek_adi = request.form.get('yemek_adi')
        try: satis_fiyati = float(request.form.get('satis_fiyati', 0))
        except: satis_fiyati = 0

        if yemek_adi:
            conn.execute('INSERT INTO tarifler (isletme_id, yemek_adi, satis_fiyati) VALUES (?, ?, ?)', (isletme_id, yemek_adi, satis_fiyati))
            conn.commit()
            return redirect(url_for('tarifler'))

    sorgu = '''SELECT t.*,
               SUM(CASE WHEN m.uyari_okundu = 0 AND m.fiyat_durumu = 'artti' THEN 1 ELSE 0 END) as artan_sayisi,
               SUM(CASE WHEN m.uyari_okundu = 0 AND m.fiyat_durumu = 'dustu' THEN 1 ELSE 0 END) as dusen_sayisi,
               (SELECT SUM(CASE WHEN m2.birim IN ('kg', 'lt') THEN (m2.birim_fiyat / 1000.0) * tm2.miktar ELSE m2.birim_fiyat * tm2.miktar END)
                FROM tarif_malzemeleri tm2 JOIN malzemeler m2 ON tm2.malzeme_id = m2.id WHERE tm2.tarif_id = t.id) as toplam_maliyet
               FROM tarifler t
               LEFT JOIN tarif_malzemeleri tm ON t.id = tm.tarif_id
               LEFT JOIN malzemeler m ON tm.malzeme_id = m.id
               WHERE t.isletme_id = ?
               GROUP BY t.id ORDER BY t.id DESC'''
    tarifler_listesi = conn.execute(sorgu, (isletme_id,)).fetchall()
    conn.close()
    return render_template('tarifler.html', tarifler=tarifler_listesi)

@app.route('/tarif_satis_guncelle/<int:id>', methods=['POST'])
@login_required
def tarif_satis_guncelle(id):
    try: yeni_satis = float(request.form.get('satis_fiyati'))
    except: yeni_satis = 0
    conn = get_db_connection()
    # Güvenlik: Kendi tarifini güncelleyebilir
    conn.execute('UPDATE tarifler SET satis_fiyati = ? WHERE id = ? AND isletme_id = ?', (yeni_satis, id, session['isletme_id']))
    conn.commit(); conn.close()
    flash("Satış fiyatı başarıyla güncellendi.", "success")
    return redirect(url_for('tarif_detay', id=id))

@app.route('/tarif/<int:id>', methods=['GET', 'POST'])
@login_required
def tarif_detay(id):
    conn = get_db_connection()
    isletme_id = session['isletme_id']

    # Güvenlik: Tarifin sahibi bu işletme mi?
    tarif = conn.execute('SELECT * FROM tarifler WHERE id = ? AND isletme_id = ?', (id, isletme_id)).fetchone()
    if not tarif:
        conn.close()
        return redirect(url_for('tarifler'))

    if request.method == 'POST':
        malzeme_id = request.form.get('malzeme_id')
        try: miktar = float(request.form.get('miktar'))
        except: miktar = 0
        if miktar > 0:
            conn.execute('INSERT INTO tarif_malzemeleri (tarif_id, malzeme_id, miktar) VALUES (?, ?, ?)', (id, malzeme_id, miktar))
            conn.commit()
        return redirect(url_for('tarif_detay', id=id))

    tum_malzemeler = conn.execute('SELECT * FROM malzemeler WHERE isletme_id = ? ORDER BY ad ASC', (isletme_id,)).fetchall()

    sorgu = '''SELECT m.id AS malzeme_id, m.ad, tm.miktar, m.birim, m.birim_fiyat, m.fiyat_durumu, m.uyari_okundu,
               CASE WHEN m.birim IN ('kg', 'lt') THEN (m.birim_fiyat / 1000.0) * tm.miktar ELSE m.birim_fiyat * tm.miktar END as satir_maliyeti
               FROM tarif_malzemeleri tm JOIN malzemeler m ON tm.malzeme_id = m.id WHERE tm.tarif_id = ?'''
    kullanilan_malzemeler = conn.execute(sorgu, (id,)).fetchall()
    toplam_maliyet = sum(satir['satir_maliyeti'] for satir in kullanilan_malzemeler)
    conn.close()
    return render_template('tarif_detay.html', tarif=tarif, malzemeler=tum_malzemeler, kullanilan_malzemeler=kullanilan_malzemeler, toplam_maliyet=toplam_maliyet)

@app.route('/tariften_sil/<int:tarif_id>/<int:malzeme_id>', methods=['POST'])
@login_required
def tariften_sil(tarif_id, malzeme_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tarif_malzemeleri WHERE tarif_id = ? AND malzeme_id = ?', (tarif_id, malzeme_id))
    conn.commit(); conn.close()
    return redirect(url_for('tarif_detay', id=tarif_id))

@app.route('/tarif_sil/<int:id>', methods=['POST'])
@login_required
def tarif_sil(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tarif_malzemeleri WHERE tarif_id = ?', (id,))
    conn.execute('DELETE FROM tarifler WHERE id = ? AND isletme_id = ?', (id, session['isletme_id']))
    conn.commit(); conn.close()
    return redirect(url_for('tarifler'))

@app.route('/siparisler', methods=['GET', 'POST'])
@login_required
def siparisler():
    conn = get_db_connection()
    isletme_id = session['isletme_id']

    if request.method == 'POST':
        if siparis_adi := request.form.get('siparis_adi'):
            mevcut = conn.execute("SELECT id FROM siparisler WHERE isletme_id = ? AND siparis_adi = ? AND durum IN ('Hazırlanıyor', 'Teslim Edildi')", (isletme_id, siparis_adi)).fetchone()
            if mevcut:
                conn.close()
                return redirect(url_for('siparis_detay', id=mevcut['id']))
            conn.execute('INSERT INTO siparisler (isletme_id, siparis_adi) VALUES (?, ?)', (isletme_id, siparis_adi))
            conn.commit()
            return redirect(url_for('siparisler'))

    # DÜZELTİLEN KISIM: datetime(tarih, 'localtime') yerine TO_CHAR kullanıldı (PostgreSQL)
    aktif_siparisler = conn.execute("SELECT id, siparis_adi, durum, gun_kapandi, TO_CHAR(tarih, 'YYYY-MM-DD HH24:MI:SS') as tarih FROM siparisler WHERE isletme_id = ? AND durum IN ('Hazırlanıyor', 'Teslim Edildi') ORDER BY id DESC", (isletme_id,)).fetchall()
    gecmis_siparisler = conn.execute("SELECT id, siparis_adi, durum, gun_kapandi, TO_CHAR(tarih, 'YYYY-MM-DD HH24:MI:SS') as tarih FROM siparisler WHERE isletme_id = ? AND durum NOT IN ('Hazırlanıyor', 'Teslim Edildi') ORDER BY id DESC LIMIT 20", (isletme_id,)).fetchall()

    masalar = conn.execute('SELECT * FROM masalar WHERE isletme_id = ? ORDER BY id', (isletme_id,)).fetchall()
    dolu_masalar_listesi = [s['siparis_adi'] for s in aktif_siparisler]
    conn.close()
    return render_template('siparisler.html', aktif_siparisler=aktif_siparisler, gecmis_siparisler=gecmis_siparisler, masalar=masalar, dolu_masalar=dolu_masalar_listesi)

@app.route('/siparis/<int:id>', methods=['GET', 'POST'])
@login_required
def siparis_detay(id):
    conn = get_db_connection()
    isletme_id = session['isletme_id']

    siparis = conn.execute('SELECT * FROM siparisler WHERE id = ? AND isletme_id = ?', (id, isletme_id)).fetchone()
    if not siparis:
        conn.close()
        return redirect(url_for('siparisler'))

    if request.method == 'POST':
        tarif_id = request.form.get('tarif_id')
        try: adet = int(request.form.get('adet', 1))
        except: adet = 0

        if tarif_id and adet > 0:
            malzemeler = conn.execute('SELECT m.id, m.ad, m.stok_miktari, m.birim, tm.miktar FROM tarif_malzemeleri tm JOIN malzemeler m ON tm.malzeme_id = m.id WHERE tm.tarif_id = ?', (tarif_id,)).fetchall()

            yetersiz_stok_listesi = []
            dusulecek_stoklar = []

            for m in malzemeler:
                # KESİN ÇÖZÜM: Veritabanından gelen Decimal verileri Float'a çeviriyoruz
                stok = float(m['stok_miktari'] or 0)
                miktar = float(m['miktar'] or 0)

                harcanan = miktar * adet
                if m['birim'] in ['kg', 'lt']: harcanan = harcanan / 1000.0
                
                if stok < harcanan:
                    yetersiz_stok_listesi.append(f"• {m['ad']} (Eksik: <b>{(harcanan - stok):.2f} {m['birim']}</b>)")
                else:
                    dusulecek_stoklar.append((harcanan, m['id']))

            if yetersiz_stok_listesi:
                flash("Deponuzda bu siparişi karşılayacak yeterli malzeme yok!<br><br>" + "<br>".join(yetersiz_stok_listesi), "error")
            else:
                conn.execute('INSERT INTO siparis_detay (siparis_id, tarif_id, adet) VALUES (?, ?, ?)', (id, tarif_id, adet))
                for harcanan, m_id in dusulecek_stoklar:
                    conn.execute('UPDATE malzemeler SET stok_miktari = stok_miktari - ? WHERE id = ?', (harcanan, m_id))
                conn.commit()
                flash("Yemek adisyona eklendi ve malzemeler anında stoktan düşüldü.", "success")
        return redirect(url_for('siparis_detay', id=id))

    tum_tarifler = conn.execute('SELECT * FROM tarifler WHERE isletme_id = ? ORDER BY yemek_adi ASC', (isletme_id,)).fetchall()

    sorgu = '''SELECT sd.id as detay_id, t.yemek_adi, t.satis_fiyati, sd.adet,
               (SELECT SUM(CASE WHEN m.birim IN ('kg', 'lt') THEN (m.birim_fiyat / 1000.0) * tm.miktar ELSE m.birim_fiyat * tm.miktar END)
               FROM tarif_malzemeleri tm JOIN malzemeler m ON tm.malzeme_id = m.id WHERE tm.tarif_id = t.id) as birim_maliyet
               FROM siparis_detay sd JOIN tarifler t ON sd.tarif_id = t.id WHERE sd.siparis_id = ?'''
    kalemler = conn.execute(sorgu, (id,)).fetchall()

    islenmis_kalemler, toplam_siparis_maliyeti, toplam_siparis_satis = [], 0, 0
    for k in kalemler:
        # KESİN ÇÖZÜM: Fiyat hesaplamalarını da Float yapıyoruz
        birim = float(k['birim_maliyet'] or 0)
        satis = float(k['satis_fiyati'] or 0)
        satir_toplam_maliyet = birim * k['adet']
        satir_toplam_satis = satis * k['adet']

        toplam_siparis_maliyeti += satir_toplam_maliyet
        toplam_siparis_satis += satir_toplam_satis

        islenmis_kalemler.append({
            'detay_id': k['detay_id'], 'yemek_adi': k['yemek_adi'], 'adet': k['adet'],
            'birim_maliyet': birim, 'satir_maliyeti': satir_toplam_maliyet, 'satis_fiyati': satis
        })

    conn.close()
    return render_template('siparis_detay.html', siparis=siparis, tarifler=tum_tarifler, kalemler=islenmis_kalemler,
                           toplam_maliyet=toplam_siparis_maliyeti, toplam_satis=toplam_siparis_satis)

@app.route('/siparis_kalem_sil/<int:siparis_id>/<int:detay_id>', methods=['POST'])
@login_required
def siparis_kalem_sil(siparis_id, detay_id):
    conn = get_db_connection()
    kalem = conn.execute('SELECT tarif_id, adet FROM siparis_detay WHERE id = ?', (detay_id,)).fetchone()
    if kalem:
        malzemeler = conn.execute('SELECT malzeme_id, miktar FROM tarif_malzemeleri WHERE tarif_id = ?', (kalem['tarif_id'],)).fetchall()
        for m in malzemeler:
            mat = conn.execute('SELECT birim FROM malzemeler WHERE id = ?', (m['malzeme_id'],)).fetchone()
            
            # KESİN ÇÖZÜM: İade hesaplamasında Float
            miktar = float(m['miktar'] or 0)
            adet = int(kalem['adet'] or 0)
            iade = miktar * adet
            
            if mat['birim'] in ['kg', 'lt']: iade = iade / 1000.0
            conn.execute('UPDATE malzemeler SET stok_miktari = stok_miktari + ? WHERE id = ?', (iade, m['malzeme_id']))
    conn.execute('DELETE FROM siparis_detay WHERE id = ?', (detay_id,))
    conn.commit(); conn.close()
    return redirect(url_for('siparis_detay', id=siparis_id))

@app.route('/siparis_durum/<int:id>/<durum>', methods=['POST'])
@login_required
def siparis_durum(id, durum):
    conn = get_db_connection()
    # Güvenlik: Sadece kendi siparişinin durumunu değiştirebilir
    sip_kontrol = conn.execute('SELECT durum FROM siparisler WHERE id = ? AND isletme_id = ?', (id, session['isletme_id'])).fetchone()

    if sip_kontrol:
        if durum == 'İptal' and sip_kontrol['durum'] in ['Hazırlanıyor', 'Teslim Edildi']:
            kalemler = conn.execute('SELECT tarif_id, adet FROM siparis_detay WHERE siparis_id = ?', (id,)).fetchall()
            for k in kalemler:
                malzemeler = conn.execute('SELECT malzeme_id, miktar FROM tarif_malzemeleri WHERE tarif_id = ?', (k['tarif_id'],)).fetchall()
                for m in malzemeler:
                    mat = conn.execute('SELECT birim FROM malzemeler WHERE id = ?', (m['malzeme_id'],)).fetchone()
                    
                    # KESİN ÇÖZÜM: Komple iptal işleminde stok iadesini Float ile yapma
                    miktar = float(m['miktar'] or 0)
                    adet = int(k['adet'] or 0)
                    iade = miktar * adet
                    
                    if mat['birim'] in ['kg', 'lt']: iade = iade / 1000.0
                    conn.execute('UPDATE malzemeler SET stok_miktari = stok_miktari + ? WHERE id = ?', (iade, m['malzeme_id']))

        conn.execute('UPDATE siparisler SET durum = ? WHERE id = ?', (durum, id))
        conn.commit()
    conn.close()
    if request.args.get('next') == 'anasayfa':
        return redirect(url_for('anasayfa'))
    return redirect(url_for('siparisler'))

@app.route('/gun_sonu', methods=['POST'])
@login_required
def gun_sonu():
    conn = get_db_connection()
    isletme_id = session['isletme_id']

    ciro_query = '''
        SELECT SUM(sd.adet * t.satis_fiyati) as ciro, COUNT(DISTINCT s.id) as sip_sayisi
        FROM siparis_detay sd
        JOIN tarifler t ON sd.tarif_id = t.id
        JOIN siparisler s ON sd.siparis_id = s.id
        WHERE s.isletme_id = ? AND s.durum = 'Tamamlandı' AND s.gun_kapandi = 0
    '''
    ciro_res = conn.execute(ciro_query, (isletme_id,)).fetchone()
    
    # KESİN ÇÖZÜM: Sonuçları JSON'un anlayacağı float ve int formatına zorluyoruz
    ciro = float(ciro_res['ciro'] or 0)
    sip_sayisi = int(ciro_res['sip_sayisi'] or 0)

    maliyet_query = '''
        SELECT SUM(
            sd.adet * tm.miktar * (
                CASE WHEN m.birim IN ('kg', 'lt') THEN m.birim_fiyat / 1000.0 ELSE m.birim_fiyat END
            )
        ) as maliyet
        FROM siparis_detay sd
        JOIN siparisler s ON sd.siparis_id = s.id
        JOIN tarif_malzemeleri tm ON sd.tarif_id = tm.tarif_id
        JOIN malzemeler m ON tm.malzeme_id = m.id
        WHERE s.isletme_id = ? AND s.durum = 'Tamamlandı' AND s.gun_kapandi = 0
    '''
    maliyet_res = conn.execute(maliyet_query, (isletme_id,)).fetchone()
    maliyet = float(maliyet_res['maliyet'] or 0) # Burada da float dönüşümü yapıldı

    kar = float(ciro - maliyet)

    conn.execute("UPDATE siparisler SET gun_kapandi = 1 WHERE isletme_id = ? AND durum = 'Tamamlandı' AND gun_kapandi = 0", (isletme_id,))
    conn.commit()
    conn.close()

    return {"ciro": ciro, "maliyet": maliyet, "kar": kar, "siparis_sayisi": sip_sayisi}

# ==========================================
# 6. YARDIMCI ROTALAR
# ==========================================
@app.route('/fiyat_gecmisi/<int:id>')
@login_required
def get_fiyat_gecmisi(id):
    conn = get_db_connection()
    gecmis = conn.execute('SELECT * FROM fiyat_gecmisi WHERE malzeme_id = ? ORDER BY degisim_tarihi DESC', (id,)).fetchall()
    conn.close()
    return {"gecmis": [dict(row) for row in gecmis]}

@app.route('/uyari_kapat_malzeme/<int:id>', methods=['POST'])
@login_required
def uyari_kapat_malzeme(id):
    conn = get_db_connection()
    conn.execute('UPDATE malzemeler SET uyari_okundu = 1 WHERE id = ? AND isletme_id = ?', (id, session['isletme_id']))
    conn.commit(); conn.close()
    return {"durum": "basarili"}

@app.route('/uyari_kapat_tarif/<int:id>', methods=['POST'])
@login_required
def uyari_kapat_tarif(id):
    conn = get_db_connection()
    conn.execute('UPDATE malzemeler SET uyari_okundu = 1 WHERE id IN (SELECT malzeme_id FROM tarif_malzemeleri tm JOIN tarifler t ON tm.tarif_id = t.id WHERE t.id = ? AND t.isletme_id = ?)', (id, session['isletme_id']))
    conn.commit(); conn.close()
    return {"durum": "basarili"}

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

import psycopg2
from werkzeug.security import generate_password_hash
import os

def veritabani_kur():
    # DATABASE_URL ortam değişkeninden okunur (Render/Neon panelinden ayarlanmalıdır)
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("HATA: DATABASE_URL ortam değişkeni tanımlanmamış! Lütfen ortam değişkenini ayarlayın.")
        return
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS isletmeler (id SERIAL PRIMARY KEY, isletme_adi TEXT NOT NULL UNIQUE, parola TEXT NOT NULL, adres TEXT, rol TEXT DEFAULT 'isletme', paket_tipi TEXT DEFAULT 'Ücretsiz')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS malzemeler (id SERIAL PRIMARY KEY, isletme_id INTEGER NOT NULL, ad TEXT NOT NULL, birim TEXT NOT NULL, birim_fiyat NUMERIC NOT NULL, stok_miktari NUMERIC DEFAULT 0, fiyat_durumu TEXT DEFAULT 'sabit', uyari_okundu INTEGER DEFAULT 1, son_guncelleme TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarifler (id SERIAL PRIMARY KEY, isletme_id INTEGER NOT NULL, yemek_adi TEXT NOT NULL, satis_fiyati NUMERIC DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarif_malzemeleri (id SERIAL PRIMARY KEY, tarif_id INTEGER, malzeme_id INTEGER, miktar NUMERIC NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS fiyat_gecmisi (id SERIAL PRIMARY KEY, malzeme_id INTEGER, eski_fiyat NUMERIC, degisim_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS siparisler (id SERIAL PRIMARY KEY, isletme_id INTEGER NOT NULL, siparis_adi TEXT NOT NULL, durum TEXT DEFAULT 'Hazırlanıyor', tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP, gun_kapandi INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS siparis_detay (id SERIAL PRIMARY KEY, siparis_id INTEGER, tarif_id INTEGER, adet INTEGER DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS masalar (id SERIAL PRIMARY KEY, isletme_id INTEGER NOT NULL, masa_adi TEXT NOT NULL)''')

    conn.commit()

    cursor.execute("SELECT id FROM isletmeler WHERE isletme_adi = 'Admin'")
    if not cursor.fetchone():
        kriptolu_parola = generate_password_hash("admin45.5")
        cursor.execute('INSERT INTO isletmeler (isletme_adi, parola, rol, adres) VALUES (%s, %s, %s, %s)', ("Admin", kriptolu_parola, "admin", "Sistem Yöneticisi"))
        conn.commit()

    conn.close()
    print("PostgreSQL Veritabanı ve Admin Hesabı Başarıyla Kuruldu!")

if __name__ == "__main__":
    veritabani_kur()
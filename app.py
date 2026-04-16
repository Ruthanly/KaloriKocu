import streamlit as st
import google.generativeai as genai
from PIL import Image
import json
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import io # Fotoğrafı bellekte küçültmek için lazım
import re # regex kütüphanesi eksikti, okuyucu için gerekli

try:
    import pandas as pd
    import plotly.express as px
    GRAFIK_AKTIF = True
except ImportError:
    GRAFIK_AKTIF = False

# ==========================================
# 0. FIREBASE BAĞLANTISI (BULUT VERİTABANI)
# ==========================================
# Firebase uygulaması daha önce başlatılmış mı diye kontrol ediyoruz
try:
    firebase_admin.get_app()
except ValueError:
    # Eğer başlatılmamışsa (ValueError verirse) sıfırdan bağlanıyoruz
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Veritabanı bağlantı hatası: Sisteme bağlanılamadı. Lütfen yöneticinizle iletişime geçin. (Hata: {e})")

# Firestore bağlantısını al
db_firestore = firestore.client()

# ==========================================
# KULLANICI GİRİŞ SİSTEMİ (BULUT DESTEKLİ)
# ==========================================
if 'aktif_kullanici' not in st.session_state:
    st.session_state.aktif_kullanici = None

if 'incelenen_kullanici' not in st.session_state:
    st.session_state.incelenen_kullanici = None

# ==========================================
# 1. AYARLAR VE YAPAY ZEKA (MALİYET OPTİMİZASYONU EKLENDİ)
# ==========================================
# Anahtarı doğrudan yazmak yerine Streamlit Secrets'tan güvenli bir şekilde çekiyoruz
API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)

# --- MALİYET DÜŞÜRME HAMLESİ 1 & 2 ---
# Pahalı modeller yerine Flash kullanıyoruz ve token (kelime) sınırı koyuyoruz.
generation_config = genai.GenerationConfig(
    max_output_tokens=250, # Sadece JSON döndüreceği için fazla kelimeye para ödemeyiz
    temperature=0.4
)

try:
    # Otomatik pahalı modeli seçmek yerine flash modeline sabitliyoruz
    model = genai.GenerativeModel('gemini-1.5-flash', generation_config=generation_config)
except Exception:
    model = None

YAYGIN_YEMEKLER = [
    "Haşlanmış Yumurta", "Sahanda Yumurta", "Menemen", "Omlet", "Haşlanmış Patates", "Patates Kızartması", "Fırın Patates",
    "Haşlanmış Tavuk", "Izgara Tavuk", "Tavuk Sote", "Tavuk Döner", "Et Döner", "İskender", "Izgara Köfte", "Sulu Köfte", "Kavurma",
    "Mercimek Çorbası", "Ezogelin Çorbası", "Tarhana Çorbası", "Tavuk Suyu Çorbası", "Pirinç Pilavı", "Bulgur Pilavı", "Domatesli Pilav",
    "Spagetti", "Salçalı Makarna", "Kıymalı Makarna", "Mantı", "Çoban Salata", "Mevsim Salata", "Tavuklu Salata", "Ton Balıklı Salata",
    "Beyaz Peynir", "Kaşar Peyniri", "Tulum Peyniri", "Siyah Zeytin", "Yeşil Zeytin", "Tereyağı", "Bal", "Çilek Reçeli", "Vişne Reçeli",
    "Beyaz Ekmek", "Tam Buğday Ekmeği", "Kepekli Ekmek", "Simit", "Poğaça", "Açma", "Börek", "Elma", "Muz", "Portakal", "Mandalina", 
    "Üzüm", "Karpuz", "Kavun", "Çilek", "Süt", "Yoğurt", "Ayran", "Kefir", "Cacık", "Çay", "Yeşil Çay", "Türk Kahvesi", "Filtre Kahve", 
    "Kola", "Meyve Suyu", "Maden Suyu", "Baklava", "Sütlaç", "Kazandibi", "Profiterol", "Dondurma", "Çikolata", "Ceviz", "Fındık", "Badem"
]

st.set_page_config(page_title="Kalori ve Koçluk", page_icon="🍏", layout="wide")

# --- LOGIN / REGISTER EKRANI ---
if st.session_state.aktif_kullanici is None:
    st.markdown("<h1 style='text-align: center; color: #2ecc71; margin-top: 50px;'>🍏 Kalori ve Koçluk Merkezi</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Devam etmek için lütfen giriş yapın veya kayıt olun.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_giris, tab_kayit = st.tabs(["🔑 Giriş Yap", "📝 Kayıt Ol"])
        
        with tab_giris:
            giris_kadi = st.text_input("Kullanıcı Adı", key="login_kadi").strip().lower()
            giris_sifre = st.text_input("Şifre", type="password", key="login_sifre")
            
            if st.button("Giriş Yap", use_container_width=True, type="primary"):
                if not giris_kadi or not giris_sifre:
                    st.warning("Lütfen alanları doldurun.")
                else:
                    if giris_kadi == "admin":
                        # İlk Admin Şifresi Kurulumu veya Giriş Kontrolü
                        kullanici_doc = db_firestore.collection("hesaplar").document("admin").get()
                        if not kullanici_doc.exists:
                            db_firestore.collection("hesaplar").document("admin").set({"sifre": giris_sifre, "kayit_tarihi": str(datetime.date.today())})
                            st.session_state.aktif_kullanici = "admin"
                            st.success("Admin hesabı şifresi başarıyla oluşturuldu ve giriş yapıldı!")
                            st.rerun()
                        else:
                            if kullanici_doc.to_dict().get("sifre") == giris_sifre:
                                st.session_state.aktif_kullanici = "admin"
                                st.session_state.incelenen_kullanici = None
                                st.success("Giriş başarılı!")
                                st.rerun()
                            else:
                                st.error("Admin şifresi hatalı!")
                    else:
                        # Normal Kullanıcı Girişi
                        kullanici_doc = db_firestore.collection("hesaplar").document(giris_kadi).get()
                        if kullanici_doc.exists and kullanici_doc.to_dict().get("sifre") == giris_sifre:
                            st.session_state.aktif_kullanici = giris_kadi
                            st.success("Giriş başarılı!")
                            st.rerun()
                        else:
                            st.error("Kullanıcı adı veya şifre hatalı!")
                    
        with tab_kayit:
            kayit_kadi = st.text_input("Yeni Kullanıcı Adı", key="reg_kadi").strip().lower()
            kayit_sifre = st.text_input("Yeni Şifre", type="password", key="reg_sifre")
            kayit_sifre_tekrar = st.text_input("Şifreyi Tekrar Girin", type="password", key="reg_sifre2")
            
            if st.button("Kayıt Ol", use_container_width=True):
                if not kayit_kadi or not kayit_sifre:
                    st.warning("Lütfen tüm alanları doldurun.")
                elif " " in kayit_kadi:
                    st.error("Kullanıcı adında boşluk olamaz!")
                elif kayit_kadi == "admin":
                    st.error("'admin' kullanıcı adı buradan kaydedilemez. Giriş yap ekranından ilk şifrenizi belirleyin.")
                elif kayit_sifre != kayit_sifre_tekrar:
                    st.error("Şifreler eşleşmiyor!")
                else:
                    kullanici_ref = db_firestore.collection("hesaplar").document(kayit_kadi)
                    if kullanici_ref.get().exists:
                        st.error("Bu kullanıcı adı zaten alınmış!")
                    else:
                        kullanici_ref.set({"sifre": kayit_sifre, "kayit_tarihi": str(datetime.date.today())})
                        # İlk veritabanı iskeletini oluştur
                        db_firestore.collection("kullanici_verileri").document(kayit_kadi).set({"profil": {"isim": kayit_kadi}, "gecmis": {}})
                        st.success("Kayıt başarılı! Şimdi giriş yapabilirsiniz.")

# --- ROUTING MANTIĞI: ADMIN Mİ, NORMAL KULLANICI MI, YOKSA ADMIN İNCELEMEDE Mİ? ---
else:
    is_admin_viewing = False
    kullanici_adi = st.session_state.aktif_kullanici

    if kullanici_adi == "admin" and not st.session_state.get("incelenen_kullanici"):
        # ==========================================
        # YÖNETİCİ (ADMIN) PANELİ ANA EKRANI
        # ==========================================
        with st.sidebar:
            st.title("👑 Admin Paneli")
            st.write("---")
            if st.button("🚪 Çıkış Yap", use_container_width=True, type="primary"):
                st.session_state.aktif_kullanici = None
                st.rerun()

        st.markdown("<h2 style='text-align: center; color: #e74c3c;'>👑 Yönetici (Admin) Paneli</h2>", unsafe_allow_html=True)
        st.divider()
        st.markdown("### 👥 Kayıtlı Kullanıcılar ve Durumları")
        
        hesaplar = db_firestore.collection("hesaplar").stream()
        
        for hesap in hesaplar:
            kadi = hesap.id
            if kadi == "admin": continue
                
            veri_doc = db_firestore.collection("kullanici_verileri").document(kadi).get()
            sifre_text = hesap.to_dict().get("sifre", "Bilinmiyor")
            
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 3, 3, 2])
                c1.markdown(f"#### 👤 {kadi}")
                
                if veri_doc.exists:
                    u_data = veri_doc.to_dict()
                    profil = u_data.get("profil", {})
                    gecmis = u_data.get("gecmis", {})
                    
                    kilo = float(profil.get("kilo", profil.get("baslangic_kilo", 0)))
                    baslangic = float(profil.get("baslangic_kilo", 0))
                    hedef = float(profil.get("hedef_kilo", 0))
                    isim = profil.get("isim", kadi)
                    kayitli_gun = len(gecmis.keys())
                    
                    verilen = baslangic - kilo
                    
                    c2.write(f"**İsim:** {isim}")
                    c2.write(f"**Şifre:** `{sifre_text}`")
                    c2.write(f"**Aktif Gün:** {kayitli_gun}")
                    
                    c3.write(f"**Başlangıç:** {baslangic} kg")
                    c3.write(f"**Güncel:** {kilo} kg")
                    c3.write(f"**Hedef:** {hedef} kg")
                    c3.write(f"**Verilen:** {verilen:.1f} kg")
                    
                    if (baslangic - hedef) > 0:
                        oran = max(0.0, min(verilen / (baslangic - hedef), 1.0))
                        c3.progress(oran, text=f"Hedefe Ulaşma: %{oran * 100:.1f}")
                        
                    st.markdown("<br>", unsafe_allow_html=True)
                    if c4.button("🔍 Paneli İncele", key=f"view_{kadi}", type="secondary", use_container_width=True):
                        st.session_state.incelenen_kullanici = kadi
                        st.rerun()
                else:
                    c2.info("Veri girilmemiş.")
                    c2.write(f"**Şifre:** `{sifre_text}`")

    else:
        # ==========================================
        # ANA UYGULAMA (Kullanıcılar veya İnceleyen Admin İçin)
        # ==========================================
        if kullanici_adi == "admin" and st.session_state.get("incelenen_kullanici"):
            kullanici_adi = st.session_state.incelenen_kullanici
            is_admin_viewing = True

        doc_ref = db_firestore.collection("kullanici_verileri").document(kullanici_adi)

        # Verileri buluttan çekme fonksiyonu
        def verileri_yukle_bulut():
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            else:
                varsayilan = {"profil": {"isim": "Ali Kaan Tüfekçi" if kullanici_adi == "ruthanly" else kullanici_adi}, "gecmis": {}}
                doc_ref.set(varsayilan)
                return varsayilan

        # Verileri buluta kaydetme fonksiyonu
        def verileri_kaydet_bulut(data):
            if not is_admin_viewing:
                doc_ref.set(data)

        # Session State'e verileri al
        if 'db' not in st.session_state or st.session_state.get('db_user') != kullanici_adi:
            st.session_state.db = verileri_yukle_bulut()
            st.session_state.db_user = kullanici_adi
            
        db = st.session_state.db

        def gunluk_toplam_guncelle(tarih):
            if not is_admin_viewing:
                top_k = sum(ogun.get("toplam_kalori", 0) for ogun in db["gecmis"][tarih].get("ogünler", []))
                top_p = sum(ogun.get("toplam_p", 0) for ogun in db["gecmis"][tarih].get("ogünler", []))
                top_c = sum(ogun.get("toplam_c", 0) for ogun in db["gecmis"][tarih].get("ogünler", []))
                top_y = sum(ogun.get("toplam_y", 0) for ogun in db["gecmis"][tarih].get("ogünler", []))
                
                db["gecmis"][tarih]["toplam"] = top_k
                db["gecmis"][tarih]["toplam_p"] = top_p
                db["gecmis"][tarih]["toplam_c"] = top_c
                db["gecmis"][tarih]["toplam_y"] = top_y
                verileri_kaydet_bulut(db)

        # AI Okuyucu
        def ai_metnini_parcala(satir):
            satir = satir.strip()
            if not satir.startswith('-'): return None
            
            content = satir[1:].replace('**', '').strip()
            ad_kismi = content
            degerler_kismi = content
            
            if ":" in content:
                parts = content.split(":", 1)
                ad_kismi = parts[0].strip()
                degerler_kismi = parts[1].strip()
            elif "-" in content:
                parts = content.rsplit("-", 1)
                ad_kismi = parts[0].strip()
                degerler_kismi = parts[1].strip()
                
            degerler_kismi = re.sub(r'(\d)[.,](\d{3})\b', r'\1\2', degerler_kismi)
            
            k_m = re.search(r'(\d+)\s*(?:kcal|kalori|kal|cal)', degerler_kismi, re.IGNORECASE)
            kalori = int(k_m.group(1)) if k_m else 0
            
            p_m = re.search(r'(\d+)\s*(?:g\s*|gr\s*)?(?:p\b|protein)', degerler_kismi, re.IGNORECASE)
            p_val = int(p_m.group(1)) if p_m else 0
            
            c_m = re.search(r'(\d+)\s*(?:g\s*|gr\s*)?(?:k\b|c\b|karb|karbonhidrat)', degerler_kismi, re.IGNORECASE)
            c_val = int(c_m.group(1)) if c_m else 0
            
            y_m = re.search(r'(\d+)\s*(?:g\s*|gr\s*)?(?:y\b|yağ|yag)', degerler_kismi, re.IGNORECASE)
            y_val = int(y_m.group(1)) if y_m else 0
            
            if kalori == 0 and p_val == 0 and c_val == 0 and y_val == 0:
                sayilar = re.findall(r'\d+', degerler_kismi)
                if len(sayilar) >= 4:
                    kalori, p_val, c_val, y_val = int(sayilar[-4]), int(sayilar[-3]), int(sayilar[-2]), int(sayilar[-1])
                elif len(sayilar) >= 1:
                    kalori = int(sayilar[-1])
                    
            if ":" not in content:
                m = re.search(r'\d', content)
                if m:
                    ad_kismi = content[:m.start()].strip()
                    if ad_kismi.endswith(('-', ',', '|', '(')):
                        ad_kismi = ad_kismi[:-1].strip()
                        
            return {"ad": ad_kismi, "kalori": kalori, "p": p_val, "c": c_val, "y": y_val}

        # ==========================================
        # ANA EKRAN NAVİGASYONU
        # ==========================================
        if is_admin_viewing:
            st.warning(f"👁️ ŞU AN İZLEME MODUNDASINIZ: Kullanıcı **{kullanici_adi}** paneli görüntüleniyor. Veri değiştirme butonları gizlenmiştir.")

        st.markdown("<h3 style='text-align: center; color: #2ecc71; margin-top: -30px;'>🍏 Kalori ve Koçluk Merkezi</h3>", unsafe_allow_html=True)
        col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
        with col_nav2:
            aktif_sayfa = st.radio("Menü:", ["📅 Günlük Takip", "🤖 Koçluk Merkezi"], horizontal=True, label_visibility="collapsed")
        st.write("") 

        # ==========================================
        # 2. TEMEL DEĞİŞKENLER VE HESAPLAMALAR
        # ==========================================
        p = db["profil"]

        isim = p.get("isim", kullanici_adi)
        kilo = float(p.get("kilo", p.get("baslangic_kilo", 80.0)))
        boy = int(p.get("boy", 175))
        cinsiyet = p.get("cinsiyet", "Erkek")
        baslangic = float(p.get("baslangic_kilo", 80.0))
        hedef_kilo = float(p.get("hedef_kilo", 70.0))
        hedef_gun = int(p.get("hedef_gun", 30))

        try: dt_val = datetime.datetime.strptime(p.get("dogum_tarihi", "2000-01-01"), "%Y-%m-%d").date()
        except: dt_val = datetime.date(2000, 1, 1)
        today = datetime.date.today()
        yas = today.year - dt_val.year - ((today.month, today.day) < (dt_val.month, dt_val.day))

        verilen_kilo = baslangic - kilo
        toplam_verilecek = kilo - hedef_kilo

        bmr = (10 * kilo) + (6.25 * boy) - (5 * yas) + (5 if cinsiyet == "Erkek" else -161)
        tdee = bmr * 1.3 

        hedef_toplam_acik = 0
        if toplam_verilecek > 0 and hedef_gun > 0:
            orijinal_gunluk_limit = int(tdee - ((toplam_verilecek * 7700) / hedef_gun))
            acik_olusturma = int(tdee - orijinal_gunluk_limit)
            hedef_toplam_acik = toplam_verilecek * 7700
        else:
            orijinal_gunluk_limit = int(tdee)
            acik_olusturma = 0

        hedef_su_litre = round(kilo * 0.035, 1)
        hedef_protein = int(kilo * 1.8)
        hedef_yag = int((orijinal_gunluk_limit * 0.25) / 9) 
        hedef_karb = int((orijinal_gunluk_limit - (hedef_protein * 4) - (hedef_yag * 9)) / 4)

        # ==========================================
        # 3. YAN MENÜ: PROFİL
        # ==========================================
        with st.sidebar:
            if is_admin_viewing:
                if st.button("⬅️ Admin Paneline Dön", type="primary", use_container_width=True):
                    st.session_state.incelenen_kullanici = None
                    st.rerun()
                st.write("---")

            st.title(f"👤 {isim}")
            if not is_admin_viewing:
                if st.button("🚪 Çıkış Yap", use_container_width=True, type="primary"):
                    st.session_state.aktif_kullanici = None
                    st.rerun()
                
            st.write("---")
            st.title("⚙️ Profil Ayarları")
            
            def profil_kaydet(k, v_key):
                if not is_admin_viewing:
                    v = st.session_state[v_key]
                    db["profil"][k] = str(v) if isinstance(v, datetime.date) else v
                    if k == "kilo": db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
                    verileri_kaydet_bulut(db)
                
            def profil_sil(k):
                if not is_admin_viewing:
                    if k in db["profil"]:
                        del db["profil"][k]
                        verileri_kaydet_bulut(db)
                    
            def hizala(): st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)

            with st.expander("👤 Kişisel Bilgiler", expanded=False):
                c1, c2 = st.columns([5,2])
                c1.text_input("İsim", p.get("isim", kullanici_adi), key="w_isim", on_change=profil_kaydet, args=("isim", "w_isim"), disabled=is_admin_viewing)
                with c2: 
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_isim", use_container_width=True): profil_sil("isim"); st.rerun()

                c1, c2 = st.columns([5,2])
                c1.selectbox("Cinsiyet", ["Erkek", "Kadın"], index=0 if p.get("cinsiyet", "Erkek") == "Erkek" else 1, key="w_cins", on_change=profil_kaydet, args=("cinsiyet", "w_cins"), disabled=is_admin_viewing)
                with c2: 
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_cins", use_container_width=True): profil_sil("cinsiyet"); st.rerun()
                
                c1, c2 = st.columns([5,2])
                c1.date_input("Doğum Tarihi", dt_val, min_value=datetime.date(1940,1,1), key="w_dt", on_change=profil_kaydet, args=("dogum_tarihi", "w_dt"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_dt", use_container_width=True): profil_sil("dogum_tarihi"); st.rerun()
                    
                st.markdown(f"<div style='font-size: 13px; color: gray; margin-top: -10px; margin-bottom: 10px;'>Yaşınız: {yas}</div>", unsafe_allow_html=True)

                c1, c2 = st.columns([5,2])
                c1.number_input("Boy (cm)", 100, 250, int(p.get("boy", 175)), key="w_boy", on_change=profil_kaydet, args=("boy", "w_boy"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_boy", use_container_width=True): profil_sil("boy"); st.rerun()

                c1, c2 = st.columns([5,2])
                c1.number_input("Başlangıç Kilosu (kg)", 30.0, 250.0, float(p.get("baslangic_kilo", 80.0)), step=0.1, key="w_bk", on_change=profil_kaydet, args=("baslangic_kilo", "w_bk"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_bk", use_container_width=True): profil_sil("baslangic_kilo"); st.rerun()
                    
                if not is_admin_viewing and st.button("💾 Kaydet", key="btn_kaydet_fiz", use_container_width=True):
                    verileri_kaydet_bulut(db)
                    st.success("Kişisel bilgiler kaydedildi!")

            with st.expander("⚖️ Güncel Kilo Takibi", expanded=True):
                st.markdown(f"<small style='color:gray;'>Başlangıç Kilonuz: <b>{baslangic} kg</b></small>", unsafe_allow_html=True)
                st.number_input("Güncel Kilo (kg)", 30.0, 250.0, kilo, step=0.1, key="w_gk", on_change=profil_kaydet, args=("kilo", "w_gk"), disabled=is_admin_viewing)
                
                if not is_admin_viewing:
                    col_btn1, col_btn2 = st.columns(2)
                    if col_btn1.button("🔄 Sıfırla", use_container_width=True):
                        profil_sil("kilo")
                        profil_sil("son_kilo_guncelleme")
                        st.rerun()
                        
                    if col_btn2.button("💾 Kaydet", key="btn_kaydet_kilo", use_container_width=True):
                        db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
                        verileri_kaydet_bulut(db)
                        st.success("Kilo güncellendi!")

            with st.expander("🎯 Hedeflerim", expanded=False):
                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Kilo (kg)", 30.0, 200.0, float(p.get("hedef_kilo", 70.0)), step=0.1, key="w_hk", on_change=profil_kaydet, args=("hedef_kilo", "w_hk"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_hk", use_container_width=True): profil_sil("hedef_kilo"); st.rerun()

                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Süre (Gün)", 1, 730, int(p.get("hedef_gun", 30)), key="w_hg", on_change=profil_kaydet, args=("hedef_gun", "w_hg"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_hg", use_container_width=True): profil_sil("hedef_gun"); st.rerun()
                    
                if not is_admin_viewing and st.button("💾 Kaydet", key="btn_kaydet_hedef", use_container_width=True):
                    verileri_kaydet_bulut(db)
                    st.success("Hedefler kaydedildi!")

            st.divider()
            st.markdown("### 🧬 Metabolik Detaylar")
            st.markdown(f"""
            <div style="background-color: #262730; padding: 15px; border-radius: 10px; font-size: 14px; line-height: 1.6;">
                <span style="color:#bdc3c7;">Bazal Metabolizma (BMR):</span> <b style="color:#2ecc71; float:right;">{int(bmr)} kcal</b><br>
                <span style="color:#bdc3c7;">Kilo Koruma Kalorisi:</span> <b style="color:#f1c40f; float:right;">{int(tdee)} kcal</b><br>
                <span style="color:#bdc3c7;">Hedef İçin Max Kalori:</span> <b style="color:#e74c3c; float:right;">{int(orijinal_gunluk_limit)} kcal</b><br>
                <hr style="margin: 8px 0; border-color: #3b3c45;">
                <span style="color:#bdc3c7;">Gereken Günlük Açık:</span> <b style="color:#3498db; float:right;">{acik_olusturma} kcal</b>
            </div>
            """, unsafe_allow_html=True)

            st.divider()
            st.markdown("### 🏆 Başarı Merkezi")
            
            toplam_acik_panel = 0
            for tarih, veri in db["gecmis"].items():
                net_alinan = veri.get("toplam", 0) - veri.get("yakilan_kalori", 0)
                if veri.get("toplam", 0) > 0: 
                    toplam_acik_panel += int(tdee) - net_alinan
                    
            if hedef_toplam_acik > 0:
                ilerleme_orani = max(0.0, min(toplam_acik_panel / hedef_toplam_acik, 1.0))
            else:
                ilerleme_orani = 0.0
            
            m_c1, m_c2 = st.columns(2)
            m_c1.metric("Verilen", f"{verilen_kilo:.1f} kg")
            m_c2.metric("Kalan", f"{toplam_verilecek:.1f} kg")
            st.progress(ilerleme_orani, text=f"Hedefe Ulaşma: %{ilerleme_orani * 100:.4f}")

        # ==========================================
        # 4. SAYFA YÖNLENDİRMESİ İÇERİĞİ
        # ==========================================

        if aktif_sayfa == "📅 Günlük Takip":
            
            if 'secili_tarih' not in st.session_state:
                st.session_state.secili_tarih = datetime.date.today()

            with st.container(border=True):
                col_btn_geri, col_tarih, col_btn_ileri = st.columns([1, 2, 1])
                
                with col_btn_geri:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("◀ Önceki Gün", use_container_width=True):
                        st.session_state.secili_tarih -= datetime.timedelta(days=1)
                        st.rerun()
                        
                with col_tarih:
                    st.session_state.secili_tarih = st.date_input("📅 Çalıştığınız Tarihi Seçin:", value=st.session_state.secili_tarih, max_value=datetime.date.today())
                    islem_tarihi = str(st.session_state.secili_tarih)
                    
                with col_btn_ileri:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.session_state.secili_tarih < datetime.date.today():
                        if st.button("Sonraki Gün ▶", use_container_width=True):
                            st.session_state.secili_tarih += datetime.timedelta(days=1)
                            st.rerun()

                if islem_tarihi not in db["gecmis"]: 
                    db["gecmis"][islem_tarihi] = {"toplam": 0, "toplam_p": 0, "toplam_c": 0, "toplam_y": 0, "ogünler": [], "su_litre": 0.0, "egzersizler": [], "yakilan_kalori": 0}
                    db["gecmis"][islem_tarihi]["su_hedef"] = hedef_su_litre
                    verileri_kaydet_bulut(db)
                
                db["gecmis"][islem_tarihi].setdefault("egzersizler", [])
                db["gecmis"][islem_tarihi].setdefault("yakilan_kalori", 0)

                dun_obj = st.session_state.secili_tarih - datetime.timedelta(days=1)
                dun_str = str(dun_obj)
                
                gunluk_limit = orijinal_gunluk_limit 
                
                if dun_str in db["gecmis"]:
                    dun_veri = db["gecmis"][dun_str]
                    dun_su = dun_veri.get("su_litre", 0)
                    dun_su_hedef = dun_veri.get("su_hedef", 2.5)
                    
                    if dun_su < dun_su_hedef:
                        st.warning(f"💧 **{isim}, Dünkü Su Eksikliği:** Dün hedeflenen suyu tamamlayamadın ({dun_su}L / {dun_su_hedef}L). Vücudunun susuz kalmaması için bugün hedefine ({hedef_su_litre} L) ulaşmaya özen göster!")

                    dun_alinan = dun_veri.get("toplam", 0)
                    dun_yakilan = dun_veri.get("yakilan_kalori", 0)
                    dun_net = max(0, dun_alinan - dun_yakilan)
                    
                    if dun_alinan > 0: 
                        fark = dun_net - orijinal_gunluk_limit
                        if fark > 0:
                            telafi = fark // 3
                            gunluk_limit = orijinal_gunluk_limit - telafi 
                            st.warning(f"⚖️ **{isim}, Dünkü Kaçamak:** Dün hedefini yaklaşık **{fark} kcal** aştın. Motivasyonunu asla kaybetme! Bu artışı 3 güne yayarak rahatça telafi edeceğiz. Bugünkü hedeften **{telafi} kcal** kısıldı.")
                        elif fark <= 0:
                            st.success(f"🎉 **Harika İş Çıkardın {isim}:** Dün hedefine tam sadık kaldın ve **{abs(fark)} kcal** ekstra açık yarattın. Aynen böyle devam et!")

                son_kilo_tarihi_str = p.get("son_kilo_guncelleme", "")
                if son_kilo_tarihi_str:
                    son_kilo_tarihi = datetime.datetime.strptime(son_kilo_tarihi_str, "%Y-%m-%d").date()
                    gecen_gun = (datetime.date.today() - son_kilo_tarihi).days
                    if gecen_gun >= 10:
                        st.info(f"📌 **{isim}, Ufak Bir Öneri:** Kilonu en son {gecen_gun} gün önce güncelledin. Sol panelden yeni kilonu girmek isteyebilirsin.")

            with st.container(border=True):
                col_ozet, col_su = st.columns([3, 2])

                with col_ozet:
                    st.markdown(f"#### 📊 {islem_tarihi} Özeti")

                    alinan_k = db["gecmis"][islem_tarihi].get("toplam", 0)
                    yakilan_k = db["gecmis"][islem_tarihi].get("yakilan_kalori", 0)
                    alinan_p = db["gecmis"][islem_tarihi].get("toplam_p", 0)
                    alinan_c = db["gecmis"][islem_tarihi].get("toplam_c", 0)
                    alinan_y = db["gecmis"][islem_tarihi].get("toplam_y", 0)
                    
                    net_kalori = max(0, alinan_k - yakilan_k)
                    kalan_k = max(0, gunluk_limit - net_kalori)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("🔥 Alınan", f"{alinan_k} kcal")
                    c2.metric("🏃 Yakılan", f"{yakilan_k} kcal")
                    c3.metric("🎯 Hedef", f"{gunluk_limit} kcal")
                    c4.metric("✅ Kalan", f"{kalan_k} kcal", delta=f"{kalan_k} kcal" if kalan_k > 0 else "Sınır Aşıldı!", delta_color="normal" if kalan_k > 0 else "inverse")
                    st.progress(min(net_kalori / gunluk_limit if gunluk_limit > 0 else 0, 1.0))

                    st.markdown("##### 🥩 Besin Değerleri (Makrolar)")
                    m1, m2, m3 = st.columns(3)
                    
                    with m1:
                        if alinan_p > hedef_protein:
                            st.markdown(f"<span style='color:#e74c3c;'><b>Protein: {alinan_p}g / {hedef_protein}g (Aşıldı!)</b></span>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"**Protein:** {alinan_p}g / {hedef_protein}g")
                        st.progress(min(alinan_p / hedef_protein if hedef_protein > 0 else 0, 1.0))
                        
                    with m2:
                        if alinan_c > hedef_karb:
                            st.markdown(f"<span style='color:#e74c3c;'><b>Karb: {alinan_c}g / {hedef_karb}g (Aşıldı!)</b></span>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"**Karb:** {alinan_c}g / {hedef_karb}g")
                        st.progress(min(alinan_c / hedef_karb if hedef_karb > 0 else 0, 1.0))
                        
                    with m3:
                        if alinan_y > hedef_yag:
                            st.markdown(f"<span style='color:#e74c3c;'><b>Yağ: {alinan_y}g / {hedef_yag}g (Aşıldı!)</b></span>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"**Yağ:** {alinan_y}g / {hedef_yag}g")
                        st.progress(min(alinan_y / hedef_yag if hedef_yag > 0 else 0, 1.0))

                with col_su:
                    st.markdown("#### 💧 Su Takibi")
                    mevcut_su = db["gecmis"][islem_tarihi].get("su_litre", 0.0)
                    
                    st.metric("İçilen Su", f"{mevcut_su:.2f} L", f"Hedef: {hedef_su_litre} L", delta_color="off")
                    st.progress(min(mevcut_su / hedef_su_litre if hedef_su_litre > 0 else 0, 1.0))
                    st.write("") 
                    
                    def su_ekle(miktar):
                        db["gecmis"][islem_tarihi]["su_litre"] = round(db["gecmis"][islem_tarihi].get("su_litre", 0.0) + miktar, 2)
                        verileri_kaydet_bulut(db)

                    if not is_admin_viewing:
                        btn_s1, btn_s2, btn_s3 = st.columns(3)
                        with btn_s1:
                            if st.button("🥛 +200ml", use_container_width=True):
                                su_ekle(0.2)
                                st.rerun()
                        with btn_s2:
                            if st.button("🍼 +500ml", use_container_width=True):
                                su_ekle(0.5)
                                st.rerun()
                        with btn_s3:
                            if st.button("🔄 Sıfırla", use_container_width=True):
                                db["gecmis"][islem_tarihi]["su_litre"] = 0.0
                                verileri_kaydet_bulut(db)
                                st.rerun()

            if not is_admin_viewing:
                with st.container(border=True):
                    st.markdown(f"#### 🍽️ Yiyecek Ekle")

                    if 'tabak_listesi' not in st.session_state: st.session_state.tabak_listesi = []
                    if 'onay_bekleyen_metin' not in st.session_state: st.session_state.onay_bekleyen_metin = None
                    if 'kaydedilecek_ogun_tipi' not in st.session_state: st.session_state.kaydedilecek_ogun_tipi = "Öğün"
                    if 'json_veri' not in st.session_state: st.session_state.json_veri = []
                    if 'onay_kalori' not in st.session_state: st.session_state.onay_kalori = 0
                    if 'onay_p' not in st.session_state: st.session_state.onay_p = 0
                    if 'onay_c' not in st.session_state: st.session_state.onay_c = 0
                    if 'onay_y' not in st.session_state: st.session_state.onay_y = 0

                    if st.session_state.onay_bekleyen_metin:
                        st.warning(f"🤖 AI {st.session_state.kaydedilecek_ogun_tipi} öğününü ve makroları hesapladı. Onaylıyor musun?")
                        st.info(st.session_state.onay_bekleyen_metin.replace('\n', '\n\n'))
                        
                        c_evet, c_hayir = st.columns(2)
                        
                        if c_evet.button("✅ Evet (Tabağa Ekle)", use_container_width=True):
                            yeni_ogun = {
                                "tip": st.session_state.kaydedilecek_ogun_tipi, 
                                "kalemler": st.session_state.json_veri, 
                                "toplam_kalori": st.session_state.onay_kalori, 
                                "toplam_p": st.session_state.onay_p,
                                "toplam_c": st.session_state.onay_c, 
                                "toplam_y": st.session_state.onay_y
                            }
                            db["gecmis"][islem_tarihi]["ogünler"].append(yeni_ogun)
                            gunluk_toplam_guncelle(islem_tarihi) 
                            st.session_state.tabak_listesi = []
                            st.session_state.onay_bekleyen_metin = None
                            st.session_state.json_veri = []
                            st.rerun()
                            
                        if c_hayir.button("❌ Hayır (İptal/Düzenle)", use_container_width=True):
                            st.session_state.onay_bekleyen_metin = None
                            st.session_state.json_veri = []
                            st.rerun()

                    else:
                        tab_liste, tab_foto, tab_manuel = st.tabs(["📝 Liste ve Yazı İle", "📸 Fotoğraftan Tanı", "✍️ Sadece Kalori Gir"])

                        with tab_liste:
                            ogun_tipi_liste = st.selectbox("Hangi öğünü ekliyorsun?", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün", "Atıştırmalık"], key="liste_ogun_tipi")
                            
                            st.markdown("##### 1. Yemeği Seç/Yaz")
                            secim = st.selectbox("🔍 Klavyeden arayın:", ["✍️ Listede Yok, Kendim Yazacağım"] + sorted(YAYGIN_YEMEKLER))
                            
                            if secim == "✍️ Listede Yok, Kendim Yazacağım":
                                yemek_adi = st.text_input("✏️ Ne yedin?", placeholder="Örn: Ev yapımı kek", key="ozel_yemek_adi")
                            else:
                                yemek_adi = secim
                            
                            birimler_sozlugu = {
                                "çorba": ["kase", "kepçe"], "su": ["bardak", "şişe", "litre"],
                                "ekmek": ["dilim", "adet"], "pilav": ["porsiyon", "yemek kaşığı"],
                                "makarna": ["porsiyon", "gram"], "yumurta": ["adet", "tane"],
                                "et": ["gram", "porsiyon"], "tavuk": ["gram", "porsiyon"],
                                "pizza": ["dilim", "bütün"]
                            }
                            aktif_birimler = ["porsiyon", "adet", "tane", "dilim", "kase", "bardak", "gram", "kg", "litre", "yemek kaşığı", "avuç", "kutu", "kepçe", "şişe", "dürüm", "bütün"]
                            
                            if yemek_adi:
                                for anahtar, bir_list in birimler_sozlugu.items():
                                    if anahtar in yemek_adi.lower():
                                        aktif_birimler = bir_list + [b for b in aktif_birimler if b not in bir_list]
                                        break 
                            
                            st.markdown("##### 2. Miktar")
                            col_mik, col_birim, col_ekle = st.columns([1, 2, 2])
                            miktar = col_mik.number_input("Miktar", min_value=0.01, max_value=1000.0, value=1.0, step=1.0)
                            secilen_birim = col_birim.selectbox("Birim", aktif_birimler)
                            
                            if col_ekle.button("➕ Tabağa Ekle", use_container_width=True):
                                if yemek_adi:
                                    st.session_state.tabak_listesi.append(f"{miktar} {secilen_birim} {yemek_adi}")
                                    st.rerun()

                            if st.session_state.tabak_listesi:
                                st.divider()
                                st.markdown("#### 🍱 Tabağın:")
                                for i, eleman in enumerate(st.session_state.tabak_listesi):
                                    c_yazi, c_sil = st.columns([6, 1])
                                    c_yazi.markdown(f"🍽️ {eleman}")
                                    if c_sil.button("❌", key=f"sil_tabak_{i}"):
                                        st.session_state.tabak_listesi.pop(i)
                                        st.rerun()
                                        
                                if st.button("🚀 Tabağı İncele ve Hesapla", type="primary", use_container_width=True):
                                    st.session_state.kaydedilecek_ogun_tipi = ogun_tipi_liste
                                    with st.spinner("AI tabağı inceliyor ve makroları hesaplıyor..."):
                                        liste_metni = ", ".join(st.session_state.tabak_listesi)
                                        prompt = f"""
                                        Kullanıcı şunları yedi: {liste_metni}.
                                        Görevlerin:
                                        1. Yazım hatalarını düzelt. 
                                        2. KESİNLİKLE kısaltma, özetleme yapma. Verilen listeyi ve içerikleri tam olarak koruyarak sadece gramer düzeltmesi yap.
                                        3. Her bir yiyeceğin kalorisini, Protein(p), Karbonhidrat(c) ve Yağ(y) gram değerlerini hesapla.
                                        
                                        SADECE VE SADECE AŞAĞIDAKİ GİBİ JSON FORMATINDA YANIT VER. BAŞKA HİÇBİR METİN YAZMA:
                                        [
                                          {{"ad": "[Miktar] [Birim] [Yemek Adı]", "kalori": 100, "p": 10, "c": 20, "y": 5}}
                                        ]
                                        """
                                        try:
                                            res = model.generate_content(prompt)
                                            cevap = res.text.strip()
                                            
                                            if "```json" in cevap:
                                                cevap = cevap.split("```json")[1].split("```")[0].strip()
                                            elif "```" in cevap:
                                                cevap = cevap.split("```")[1].strip()
                                                
                                            veri_listesi = json.loads(cevap)
                                            
                                            t_kal = sum(int(item.get("kalori", 0)) for item in veri_listesi)
                                            t_p = sum(int(item.get("p", 0)) for item in veri_listesi)
                                            t_c = sum(int(item.get("c", 0)) for item in veri_listesi)
                                            t_y = sum(int(item.get("y", 0)) for item in veri_listesi)
                                            
                                            gosterilecek_metin = ""
                                            for item in veri_listesi:
                                                gosterilecek_metin += f"- {item['ad']}: **{item.get('kalori', 0)} kcal** | {item.get('p', 0)}P | {item.get('c', 0)}K | {item.get('y', 0)}Y\n"
                                            
                                            gosterilecek_metin += f"\n**TOPLAM: {t_kal} kcal** | {t_p}P | {t_c}K | {t_y}Y"
                                            
                                            st.session_state.json_veri = veri_listesi
                                            st.session_state.onay_bekleyen_metin = gosterilecek_metin
                                            st.session_state.onay_kalori = t_kal
                                            st.session_state.onay_p = t_p
                                            st.session_state.onay_c = t_c
                                            st.session_state.onay_y = t_y
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Hesaplama hatası. Format bozuldu: {e}")

                        with tab_foto:
                            st.info("📸 Fotoğrafı yükle, istersen yemeğin adını yazarak AI'a ipucu ver, gerisini o halletsin!")
                            ogun_tipi_foto = st.selectbox("Öğün Seç", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün", "Atıştırmalık"], key="foto_ogun_tipi")
                            yuklenen_foto = st.file_uploader("📸 Fotoğraf Seç", type=["jpg", "jpeg", "png"])
                            ipucu = st.text_input("💡 Yemeğin ne olduğunu biliyor musun? (İsteğe bağlı ipucu)", placeholder="Örn: Ev yapımı fırın makarna, 2 dilim")
                            
                            if yuklenen_foto:
                                img = Image.open(yuklenen_foto)
                                st.image(img, use_container_width=True)
                                
                                if st.button("🚀 Analiz Et ve Makroları Hesapla", type="primary", use_container_width=True):
                                    st.session_state.kaydedilecek_ogun_tipi = ogun_tipi_foto
                                    with st.spinner("AI fotoğrafa bakıyor ve makroları hesaplıyor..."):
                                        
                                        # --- MALİYET DÜŞÜRME HAMLESİ 3: FOTOĞRAFI KÜÇÜLT ---
                                        # API'ye büyük fotoğraf göndermek faturayı şişirir. Analiz için 512px fazlasıyla yeterlidir.
                                        img_ai = img.copy()
                                        img_ai.thumbnail((512, 512), Image.Resampling.LANCZOS)
                                        
                                        ek_bilgi = f"Kullanıcı bu yemeğin '{ipucu}' olduğunu belirtti. Bu ipucundaki olası yazım ve dilbilgisi hatalarını arka planda otomatik olarak düzelt (düzeltirken KESİNLİKLE kısaltma veya özetleme yapma, içeriği tam koru). Sonra bu bilgiyi fotoğrafla eşleştirerek porsiyon ve gramaj tahmini yap." if ipucu else "Yemeği kendin tanı ve porsiyon tahmini yap."
                                        prompt = f"""
                                        Kullanıcı {st.session_state.kaydedilecek_ogun_tipi} olarak ekteki fotoğrafı yükledi.
                                        {ek_bilgi}
                                        Görevlerin:
                                        1. Fotoğraftaki yiyecekleri tespit et.
                                        2. Porsiyon/gramaj büyüklüğünü fotoğrafa göre tahmin et.
                                        3. KESİNLİKLE kısaltma, özetleme yapma. Tüm içeriği ve detayları koruyarak yaz.
                                        4. Her bir yiyeceğin kalorisini, Protein(p), Karbonhidrat(c) ve Yağ(y) gram değerlerini hesapla.
                                        
                                        SADECE VE SADECE AŞAĞIDAKİ GİBİ JSON FORMATINDA YANIT VER. BAŞKA HİÇBİR METİN YAZMA:
                                        [
                                          {{"ad": "[Tahmini Miktar] [Birim] [Yemek Adı]", "kalori": 100, "p": 10, "c": 20, "y": 5}}
                                        ]
                                        """
                                        try:
                                            res = model.generate_content([prompt, img_ai])
                                            cevap = res.text.strip()
                                            
                                            if "```json" in cevap:
                                                cevap = cevap.split("```json")[1].split("```")[0].strip()
                                            elif "```" in cevap:
                                                cevap = cevap.split("```")[1].strip()
                                                
                                            veri_listesi = json.loads(cevap)
                                            
                                            t_kal = sum(int(item.get("kalori", 0)) for item in veri_listesi)
                                            t_p = sum(int(item.get("p", 0)) for item in veri_listesi)
                                            t_c = sum(int(item.get("c", 0)) for item in veri_listesi)
                                            t_y = sum(int(item.get("y", 0)) for item in veri_listesi)
                                            
                                            gosterilecek_metin = ""
                                            for item in veri_listesi:
                                                gosterilecek_metin += f"- {item['ad']}: **{item.get('kalori', 0)} kcal** | {item.get('p', 0)}P | {item.get('c', 0)}K | {item.get('y', 0)}Y\n"
                                            
                                            gosterilecek_metin += f"\n**TOPLAM: {t_kal} kcal** | {t_p}P | {t_c}K | {t_y}Y"
                                            
                                            st.session_state.json_veri = veri_listesi
                                            st.session_state.onay_bekleyen_metin = gosterilecek_metin
                                            st.session_state.onay_kalori = t_kal
                                            st.session_state.onay_p = t_p
                                            st.session_state.onay_c = t_c
                                            st.session_state.onay_y = t_y
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Fotoğraf analiz hatası: {e}")
                            
                        with tab_manuel:
                            m_ogun = st.selectbox("Öğün", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün"], key="m_ogun")
                            m_ad = st.text_input("Yemek Adı", key="m_ad_input")
                            c1, c2, c3, c4 = st.columns(4)
                            m_k = c1.number_input("Kcal", 0, 5000, 100)
                            m_p = c2.number_input("P (g)", 0, 500, 0)
                            m_c = c3.number_input("Karb (g)", 0, 500, 0)
                            m_y = c4.number_input("Yağ (g)", 0, 500, 0)
                            
                            if st.button("Listeye Ekle", use_container_width=True) and m_ad:
                                yeni_ogun = {
                                    "tip": m_ogun, "kalemler": [{"ad": m_ad, "kalori": m_k, "p":m_p, "c":m_c, "y":m_y}], 
                                    "toplam_kalori": m_k, "toplam_p": m_p, "toplam_c": m_c, "toplam_y": m_y
                                }
                                db["gecmis"][islem_tarihi]["ogünler"].append(yeni_ogun)
                                gunluk_toplam_guncelle(islem_tarihi)
                                st.rerun()

            with st.container(border=True):
                st.markdown(f"### 📋 {islem_tarihi} Tarihli Menün")
                gunluk_veri = db["gecmis"][islem_tarihi]

                if not gunluk_veri["ogünler"]:
                    st.info(f"Bu tarihte henüz bir şey yemedin {isim}. 🍽️")
                else:
                    for m_idx, ogun in enumerate(gunluk_veri["ogünler"]):
                        with st.container(border=True):
                            c_bas, c_sil = st.columns([4, 1])
                            c_bas.markdown(f"#### 🥘 {ogun['tip']} ({ogun.get('toplam_kalori', 0)} kcal | {ogun.get('toplam_p',0)}P - {ogun.get('toplam_c',0)}K - {ogun.get('toplam_y',0)}Y)")
                            
                            if not is_admin_viewing and c_sil.button("🗑️ Tüm Öğünü Sil", key=f"del_o_{islem_tarihi}_{m_idx}"):
                                gunluk_veri["ogünler"].pop(m_idx)
                                gunluk_toplam_guncelle(islem_tarihi)
                                st.rerun()
                                
                            for k_idx, kalem in enumerate(ogun.get("kalemler", [])):
                                c_isim, c_kcal, c_makro, c_item_sil = st.columns([4, 2, 3, 1])
                                c_isim.write(f"🔹 {kalem['ad']}")
                                c_kcal.write(f"**{kalem['kalori']} kcal**")
                                c_makro.caption(f"{kalem.get('p',0)}P | {kalem.get('c',0)}K | {kalem.get('y',0)}Y")
                                
                                if not is_admin_viewing and c_item_sil.button("❌", key=f"del_i_{islem_tarihi}_{m_idx}_{k_idx}"):
                                    ogun["toplam_kalori"] -= kalem["kalori"]
                                    ogun["toplam_p"] -= kalem.get("p",0)
                                    ogun["toplam_c"] -= kalem.get("c",0)
                                    ogun["toplam_y"] -= kalem.get("y",0)
                                    ogun["kalemler"].pop(k_idx)
                                    
                                    if len(ogun["kalemler"]) == 0:
                                        gunluk_veri["ogünler"].pop(m_idx)
                                        
                                    gunluk_toplam_guncelle(islem_tarihi)
                                    st.rerun()

                    st.divider()
                    st.markdown("### 🍩 Kalori ve Makro Dağılımı")
                    col_grafik1, col_grafik2 = st.columns(2)
                    
                    ogun_toplamlari = {}
                    gunluk_p = 0
                    gunluk_c = 0
                    gunluk_y = 0
                    
                    for ogun in gunluk_veri["ogünler"]:
                        tip = ogun["tip"]
                        ogun_toplamlari[tip] = ogun_toplamlari.get(tip, 0) + ogun.get("toplam_kalori", 0)
                        gunluk_p += ogun.get("toplam_p", 0)
                        gunluk_c += ogun.get("toplam_c", 0)
                        gunluk_y += ogun.get("toplam_y", 0)

                    with col_grafik1:
                        st.markdown("<h5 style='text-align: center;'>Öğün Kalori Dağılımı</h5>", unsafe_allow_html=True)
                        if ogun_toplamlari and sum(ogun_toplamlari.values()) > 0:
                            if GRAFIK_AKTIF:
                                df_kal = pd.DataFrame(list(ogun_toplamlari.items()), columns=["Öğün", "Kalori"])
                                fig_kal = px.pie(df_kal, values="Kalori", names="Öğün", hole=0.4, color_discrete_sequence=px.colors.sequential.Teal)
                                fig_kal.update_traces(textposition='inside', textinfo='percent+label')
                                fig_kal.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=300)
                                st.plotly_chart(fig_kal, use_container_width=True)
                            else:
                                for ogun_adi, kalori in ogun_toplamlari.items():
                                    yuzde = kalori / sum(ogun_toplamlari.values())
                                    st.caption(f"**{ogun_adi}** - {kalori} kcal (%{int(yuzde*100)})")
                                    st.progress(yuzde)
                        else:
                            st.info("Henüz kalori verisi yok.")

                    with col_grafik2:
                        st.markdown("<h5 style='text-align: center;'>Makro Besin Dağılımı</h5>", unsafe_allow_html=True)
                        toplam_makro = gunluk_p + gunluk_c + gunluk_y
                        if toplam_makro > 0:
                            if GRAFIK_AKTIF:
                                df_makro = pd.DataFrame([
                                    {"Makro": "Protein", "Gram": gunluk_p},
                                    {"Makro": "Karbonhidrat", "Gram": gunluk_c},
                                    {"Makro": "Yağ", "Gram": gunluk_y}
                                ])
                                renkler = {"Protein": "#e74c3c", "Karbonhidrat": "#f1c40f", "Yağ": "#3498db"}
                                fig_makro = px.pie(df_makro, values="Gram", names="Makro", hole=0.4, color="Makro", color_discrete_map=renkler)
                                fig_makro.update_traces(textposition='inside', textinfo='percent+label')
                                fig_makro.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=300)
                                st.plotly_chart(fig_makro, use_container_width=True)
                            else:
                                st.caption(f"**Protein** - {gunluk_p}g (%{int((gunluk_p/toplam_makro)*100)})")
                                st.progress(gunluk_p/toplam_makro)
                                st.caption(f"**Karbonhidrat** - {gunluk_c}g (%{int((gunluk_c/toplam_makro)*100)})")
                                st.progress(gunluk_c/toplam_makro)
                                st.caption(f"**Yağ** - {gunluk_y}g (%{int((gunluk_y/toplam_makro)*100)})")
                                st.progress(gunluk_y/toplam_makro)
                        else:
                            st.info("Henüz makro verisi yok.")

            with st.container(border=True):
                st.markdown("### 🏃 Egzersiz ve Hareket")
                
                yakilan_toplam = db["gecmis"][islem_tarihi].get("yakilan_kalori", 0)
                
                if not db["gecmis"][islem_tarihi].get("egzersizler"):
                    st.info(f"Bugün henüz egzersiz girmedin {isim}. Hareket etmek her zaman iyidir!")
                else:
                    for e_idx, egzersiz in enumerate(db["gecmis"][islem_tarihi]["egzersizler"]):
                        c_e1, c_e2, c_e3 = st.columns([6, 2, 1])
                        sure_metni = f"{egzersiz['sure']} dk" if isinstance(egzersiz['sure'], (int, float)) else egzersiz['sure']
                        c_e1.write(f"🏋️ {egzersiz['ad']} ({sure_metni})")
                        c_e2.write(f"**🔥 {egzersiz['kalori']} kcal**")
                        if not is_admin_viewing and c_e3.button("❌", key=f"del_ex_{islem_tarihi}_{e_idx}"):
                            db["gecmis"][islem_tarihi]["yakilan_kalori"] -= egzersiz["kalori"]
                            db["gecmis"][islem_tarihi]["egzersizler"].pop(e_idx)
                            verileri_kaydet_bulut(db)
                            st.rerun()

                if not is_admin_viewing:
                    st.markdown("#### ➕ Yeni Egzersiz Ekle")
                    tab_ex_ai, tab_ex_manuel = st.tabs(["🤖 AI ile Hesapla", "✍️ Manuel Gir"])
                    
                    with tab_ex_ai:
                        ex_list = [
                            "Yürüyüş (Hafif Tempo)", "Yürüyüş (Tempolu)", "Koşu", 
                            "Bisiklet Sürme", "Motosiklet Sürme", 
                            "Ağırlık Antrenmanı", "Yüzme", "Ev İşleri / Temizlik", 
                            "Diğer (Kendim Yazacağım)"
                        ]
                        secilen_ex = st.selectbox("Egzersiz Türü:", ex_list)
                        
                        if secilen_ex == "Diğer (Kendim Yazacağım)":
                            ex_ad = st.text_input("Ne tür bir egzersiz yaptınız?", placeholder="Örn: 5 km patika yürüyüşü")
                        else:
                            ex_ad = secilen_ex
                        
                        ex_sure = st.number_input("Süre (Dakika veya Saat Karşılığı):", min_value=1, max_value=600, value=30, step=5)
                        
                        if st.button("🔥 Hesapla ve Ekle", use_container_width=True):
                            if ex_ad:
                                with st.spinner("AI yaktığın kaloriyi hesaplıyor..."):
                                    prmpt = f"Kullanıcı bilgileri: {kilo} kg, {boy} cm, {yas} yaşında, {cinsiyet}. Yaptığı egzersiz: {ex_sure} dakika boyunca {ex_ad}. SADECE YAKILAN KALORİYİ TAM SAYI OLARAK VER. Başka hiçbir harf veya kelime kullanma."
                                    try:
                                        res = model.generate_content(prmpt)
                                        kalori_burn = int(re.search(r'\d+', res.text).group())
                                        
                                        db["gecmis"][islem_tarihi]["egzersizler"].append({"ad": ex_ad, "sure": ex_sure, "kalori": kalori_burn})
                                        db["gecmis"][islem_tarihi]["yakilan_kalori"] += kalori_burn
                                        verileri_kaydet_bulut(db)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Hesaplama yapılamadı: {e}")
                    
                    with tab_ex_manuel:
                        col_m_ex1, col_m_ex2 = st.columns([3, 1])
                        m_ex_ad = col_m_ex1.text_input("Egzersiz Adı:", placeholder="Örn: Yoga")
                        m_ex_kal = col_m_ex2.number_input("Yakılan Kcal:", min_value=1, max_value=5000, value=100)
                        if st.button("Ekle", key="btn_ex_manuel", use_container_width=True):
                            if m_ex_ad:
                                db["gecmis"][islem_tarihi]["egzersizler"].append({"ad": m_ex_ad, "sure": "Manuel", "kalori": m_ex_kal})
                                db["gecmis"][islem_tarihi]["yakilan_kalori"] += m_ex_kal
                                verileri_kaydet_bulut(db)
                                st.rerun()

        # ==========================================
        # 5. KOÇLUK MERKEZİ SAYFASI
        # ==========================================
        elif aktif_sayfa == "🤖 Koçluk Merkezi":
            
            toplam_acik_koc = 0
            kayitli_gun_koc = 0
            for tarih, veri in db["gecmis"].items():
                net_alinan = veri.get("toplam", 0) - veri.get("yakilan_kalori", 0)
                if veri.get("toplam", 0) > 0: 
                    toplam_acik_koc += int(tdee) - net_alinan
                    kayitli_gun_koc += 1
                    
            yakilan_tahmini_yag_koc = toplam_acik_koc / 7700 if toplam_acik_koc > 0 else 0
            boy_m = boy / 100
            vki = kilo / (boy_m ** 2) if boy_m > 0 else 0
            
            if vki < 18.5:
                durum, renk = "Zayıf", "#e74c3c"
                alt_sinir = 0
            elif 18.5 <= vki < 24.9:
                durum, renk = "Normal", "#2ecc71"
                alt_sinir = 0
            elif 25 <= vki < 29.9:
                durum, renk = "Fazla Kilolu", "#f1c40f"
                alt_sinir = 24.9 * (boy_m ** 2)
            else:
                durum, renk = "Obez", "#e67e22"
                alt_sinir = 29.9 * (boy_m ** 2)

            with st.container(border=True):
                c_ai_yazi, c_ai_buton = st.columns([3, 1])
                c_ai_yazi.markdown("### 💬 Yapay Zeka Uzman Diyetisyen")
                c_ai_yazi.caption(f"Tüm vücut verilerini, geçmişini ve makro dağılımlarını anında analiz edip **sana özel** bir koçluk raporu hazırlar.")
                
                if not is_admin_viewing and c_ai_buton.button("🤖 Durumumu Değerlendir", use_container_width=True, type="primary"):
                    with st.spinner("Diyetisyeniniz verilerinizi inceliyor..."):
                        prompt_koc = f"""
                        Sen profesyonel, motive edici ama gerçekçi bir uzman diyetisyensin.
                        Kullanıcının Adı: {isim}
                        Cinsiyet: {cinsiyet}, Yaş: {yas}, Boy: {boy}cm, Kilo: {kilo}kg (Başlangıç: {baslangic}kg), Hedef: {hedef_kilo}kg.
                        VKİ: {vki:.1f} ({durum}). Sistemde aktif geçirdiği gün: {kayitli_gun_koc}.
                        Hedeflenen Günlük Kalori: {orijinal_gunluk_limit} kcal.
                        
                        Görev: {isim}'in bu verilerine bakarak, mevcut durumunu, hızını ve hedeflerini değerlendir. Ona kendi ismiyle ({isim}) hitap ederek özel, samimi, kısa ve tavsiye niteliğinde bir uzman görüşü yaz. (Metni KESİNLİKLE kısaltma veya özetleme, detaylı ve tam bir koçluk metni olsun. Sayın kullanıcı vb ifadeler KULLANMA, direkt ismiyle hitap et).
                        """
                        try:
                            res = model.generate_content(prompt_koc)
                            st.success("✅ Değerlendirme Tamamlandı")
                            st.write(res.text)
                        except Exception as e:
                            st.error("AI Değerlendirme sırasında bir hata oluştu.")
                            
            with st.container(border=True):
                st.markdown("### 🏆 Detaylı Başarı Dashboard'u")
                
                c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                c_m1.metric("Toplam Verilen Kilo", f"{verilen_kilo:.1f} kg", f"{baslangic} kg'dan", delta_color="off")
                c_m2.metric("Yakılan Yağ (Tahmini)", f"{yakilan_tahmini_yag_koc:.2f} kg", "Net Kalori Açığından", delta_color="off")
                c_m3.metric("Kayıtlı Gün", f"{kayitli_gun_koc} Gün", "Sistemde Aktif Süre", delta_color="off")
                c_m4.metric("Ortalama Günlük Açık", f"{int(toplam_acik_koc / kayitli_gun_koc) if kayitli_gun_koc > 0 else 0} kcal", "Gün başına", delta_color="off")
                
                if hedef_toplam_acik > 0:
                    ilerleme_orani = max(0.0, min(toplam_acik_koc / hedef_toplam_acik, 1.0))
                else:
                    ilerleme_orani = 0.0
                    
                st.progress(ilerleme_orani, text=f"Genel Hedefe Ulaşma Oranı: %{ilerleme_orani * 100:.4f}")
            
            with st.container(border=True):
                st.markdown("### 🩺 VKİ (Vücut Kitle İndeksi) Analizi")
                    
                normal_alt = 18.5 * (boy_m ** 2)
                normal_ust = 24.9 * (boy_m ** 2)
                
                st.markdown(f"**Güncel VKİ:** `{vki:.1f}` 👉 <span style='color:{renk}; font-weight:bold; font-size:18px;'>{durum}</span>", unsafe_allow_html=True)
                st.write(f"Boyunuza ({boy} cm) göre sağlıklı normal kilo aralığı: **{normal_alt:.1f} kg - {normal_ust:.1f} kg**")
                if alt_sinir > 0:
                    verilmesi_gereken = kilo - alt_sinir
                    st.info(f"💡 Bir alt risk grubuna düşmek için vermeniz gereken asgari kilo: **{verilmesi_gereken:.1f} kg** (Hedef: {alt_sinir:.1f} kg)")

            with st.container(border=True):
                st.markdown("### ⏳ Hız ve Hedef Tahmini")
                if kayitli_gun_koc > 3 and verilen_kilo > 0:
                    gunluk_hiz = verilen_kilo / kayitli_gun_koc
                    kalan_gun_tahmini = int(toplam_verilecek / gunluk_hiz) if gunluk_hiz > 0 else 0
                    tahmini_tarih = datetime.date.today() + datetime.timedelta(days=kalan_gun_tahmini)
                    st.success(f"🚀 {isim}, şu anki kilo verme hızına göre (**{gunluk_hiz:.2f} kg/gün**), hedefine **{kalan_gun_tahmini} gün sonra ({tahmini_tarih.strftime('%d.%m.%Y')})** ulaşman öngörülüyor.")
                else:
                    st.info(f"{isim}, hızını hesaplayabilmek için sistemde biraz daha veriye (en az 3-4 günlük düzenli giriş ve kilo düşüşü) ihtiyacımız var.")

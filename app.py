import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
from PIL import Image
import json
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import io 
import re 
import base64

try:
    import pandas as pd
    import plotly.express as px
    GRAFIK_AKTIF = True
except ImportError:
    GRAFIK_AKTIF = False

# ==========================================
# 0. SAYFA AYARI VE GÜVENLİ CSS KÖPRÜSÜ
# ==========================================
st.set_page_config(page_title="Kalori ve Koçluk Merkezi", page_icon="🍏", layout="wide")

st.markdown("""
<style>
/* Üst Menü Tab Görünümü */
div[role="radiogroup"] {
    display: flex; flex-direction: row; justify-content: center;
    background-color: #262730; border-radius: 10px; padding: 5px; gap: 5px;
}
div[role="radiogroup"] > label {
    flex: 1; justify-content: center; padding: 10px 5px; border-radius: 8px;
    margin: 0; background: transparent; text-align: center; border: 1px solid transparent;
}
div[role="radiogroup"] > label[data-checked="true"] { background-color: #2ecc71 !important; }
div[role="radiogroup"] > label[data-checked="true"] p { color: #1e1e1e !important; font-weight: bold; }

/* Mobil Padding Düzenleme */
@media (max-width: 768px) {
    .block-container { padding-top: 2rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
}

/* Profil Fotoğrafı Hover Etkisi Engelleme */
img.custom-pp { cursor: default !important; pointer-events: none !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 0.1. FIREBASE BAĞLANTISI
# ==========================================
try:
    firebase_admin.get_app()
except ValueError:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Veritabanı bağlantı hatası: Sisteme bağlanılamadı. Hata: {e}")

db_firestore = firestore.client()

# ==========================================
# YARDIMCI FONKSİYONLAR (RADAR JSON SİSTEMİ)
# ==========================================
if 'aktif_kullanici' not in st.session_state: st.session_state.aktif_kullanici = None
if 'incelenen_kullanici' not in st.session_state: st.session_state.incelenen_kullanici = None
if 'aktif_sayfa' not in st.session_state: st.session_state.aktif_sayfa = "📅 Günlük Takip"
if 'panel_kapat' not in st.session_state: st.session_state.panel_kapat = False

# Mobil Panel Kapatıcı JS
if st.session_state.panel_kapat:
    components.html("""<script>
        if (window.innerWidth <= 768) {
            var buttons = window.parent.document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].getAttribute('kind') === 'headerNoPadding') { buttons[i].click(); break; }
            }
        }
    </script>""", height=0, width=0)
    st.session_state.panel_kapat = False

def json_kurtar(metin):
    """AI ne yaparsa yapsın, metnin içinden sadece JSON verisini cımbızlayan Avcı/Radar sistemi."""
    try:
        # Önce markdown formatını temizle
        metin = metin.replace("```json", "").replace("```", "").strip()
        
        # Regex (Radar) ile sadece Köşeli Parantez [...] içini bul
        match_array = re.search(r'\[.*\]', metin, re.DOTALL)
        if match_array:
            metin = match_array.group(0)
        else:
            # Liste yoksa süslü parantez {...} bul
            match_obj = re.search(r'\{.*\}', metin, re.DOTALL)
            if match_obj:
                metin = match_obj.group(0)
                
        veri = json.loads(metin)
        
        # Eğer yapay zeka Dizi yerine Obje gönderdiyse
        if isinstance(veri, dict):
            # İçinde gizlenmiş liste varsa onu çıkar (Örn: {"yemekler": [...]})
            for key, val in veri.items():
                if isinstance(val, list):
                    return val
            # Yoksa objeyi listeye çevir
            return [veri]
            
        return veri
        
    except Exception as e:
        # Sistemi ÇÖKERTMEYEN güvenli hata ataması
        return [{"ad": f"⚠️ AI Formatı Bozdu (Lütfen Silip Manuel Ekleyin)", "kalori": 0, "p": 0, "c": 0, "y": 0}]

def gorsel_ilerleme(gercek_oran):
    """Küçük adımları büyük gösteren motivasyon barı (En az %5)"""
    if gercek_oran <= 0: return 0.0
    return max(0.05, min(gercek_oran, 1.0))

# ==========================================
# 1. YAPAY ZEKA VE VERİ LİSTELERİ
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)

# AI özgür bırakıldı (Multimodal fotoğraf analizinin çökmemesi için mime_type kaldırıldı)
generation_config = genai.GenerationConfig(
    max_output_tokens=2000, 
    temperature=0.2 
)

try:
    calisan_modeller = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    flash_modelleri = [m for m in calisan_modeller if 'flash' in m.lower()]
    secilen_model = flash_modelleri[0] if flash_modelleri else 'gemini-1.5-flash-latest'
    model = genai.GenerativeModel(secilen_model, generation_config=generation_config)
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

# ==========================================
# 2. LOGIN / REGISTER EKRANI
# ==========================================
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
                if giris_kadi == "admin":
                    kullanici_doc = db_firestore.collection("hesaplar").document("admin").get()
                    if not kullanici_doc.exists:
                        db_firestore.collection("hesaplar").document("admin").set({"sifre": giris_sifre, "kayit_tarihi": str(datetime.date.today())})
                        st.session_state.aktif_kullanici = "admin"; st.rerun()
                    elif kullanici_doc.to_dict().get("sifre") == giris_sifre:
                        st.session_state.aktif_kullanici = "admin"; st.rerun()
                    else: st.error("Admin şifresi hatalı!")
                else:
                    kullanici_doc = db_firestore.collection("hesaplar").document(giris_kadi).get()
                    if kullanici_doc.exists and kullanici_doc.to_dict().get("sifre") == giris_sifre:
                        st.session_state.aktif_kullanici = giris_kadi; st.rerun()
                    else: st.error("Kullanıcı adı veya şifre hatalı!")
                    
        with tab_kayit:
            kayit_kadi = st.text_input("Yeni Kullanıcı Adı", key="reg_kadi").strip().lower()
            kayit_sifre = st.text_input("Yeni Şifre", type="password", key="reg_sifre")
            kayit_sifre_tekrar = st.text_input("Şifreyi Tekrar Girin", type="password", key="reg_sifre2")
            
            if st.button("Kayıt Ol", use_container_width=True):
                if not kayit_kadi or not kayit_sifre: st.warning("Alanları doldurun.")
                elif kayit_sifre != kayit_sifre_tekrar: st.error("Şifreler eşleşmiyor!")
                else:
                    kullanici_ref = db_firestore.collection("hesaplar").document(kayit_kadi)
                    if kullanici_ref.get().exists: st.error("Bu kullanıcı adı zaten alınmış!")
                    else:
                        bugun = str(datetime.date.today())
                        kullanici_ref.set({"sifre": kayit_sifre, "kayit_tarihi": bugun})
                        db_firestore.collection("kullanici_verileri").document(kayit_kadi).set({
                            "profil": {"isim": kayit_kadi, "kayit_tarihi": bugun}, "gecmis": {}
                        })
                        st.success("Kayıt başarılı! Giriş yapabilirsiniz.")

# ==========================================
# 3. ANA UYGULAMA (YÖNLENDİRME)
# ==========================================
else:
    kullanici_adi = st.session_state.aktif_kullanici
    is_admin_viewing = False

    # ---------------------------------------------------------
    # 3.1. ADMIN PANELİ GÖRÜNÜMÜ
    # ---------------------------------------------------------
    if kullanici_adi == "admin" and not st.session_state.get("incelenen_kullanici"):
        with st.sidebar:
            st.markdown("<h3 style='text-align:center; margin-top:-20px;'>👑 Admin Paneli</h3>", unsafe_allow_html=True)
            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
            if st.button("🚪 Çıkış Yap", use_container_width=True, type="primary"):
                st.session_state.aktif_kullanici = None
                st.rerun()

        st.markdown("<h2 style='text-align: center; color: #e74c3c;'>👑 Yönetici Paneli</h2>", unsafe_allow_html=True)
        st.divider()

        st.markdown("### 🔍 Kullanıcı Ara")
        arama_metni = st.text_input("Aramak istediğiniz kullanıcı adını veya ismi yazın...", placeholder="Örn: ali veya ruthanly").strip().lower()
        st.write("")

        st.markdown("### 👥 Kayıtlı Kullanıcılar")
        
        hesaplar = db_firestore.collection("hesaplar").stream()
        bulunan_sayisi = 0
        
        for hesap in hesaplar:
            kadi = hesap.id
            if kadi == "admin": continue
                
            veri_doc = db_firestore.collection("kullanici_verileri").document(kadi).get()
            u_data = veri_doc.to_dict() if veri_doc.exists else {}
            profil = u_data.get("profil", {})
            gecmis = u_data.get("gecmis", {})
            
            isim = profil.get("isim", kadi)
            
            if arama_metni and (arama_metni not in kadi.lower() and arama_metni not in isim.lower()):
                continue
                
            bulunan_sayisi += 1
            sifre_text = hesap.to_dict().get("sifre", "Bilinmiyor")
            kayit_tarihi = hesap.to_dict().get("kayit_tarihi", "Bilinmiyor")
            
            kilo = float(profil.get("kilo", profil.get("baslangic_kilo", 0)))
            baslangic = float(profil.get("baslangic_kilo", 0))
            hedef = float(profil.get("hedef_kilo", 0))
            boy = int(profil.get("boy", 175))
            cinsiyet = profil.get("cinsiyet", "Bilinmiyor")
            kayitli_gun = len(gecmis.keys())
            verilen = baslangic - kilo
            
            boy_m = boy / 100
            vki = kilo / (boy_m ** 2) if boy_m > 0 else 0
            
            foto_b64 = profil.get("foto_base64", "")
            
            with st.expander(f"👤 {isim} (@{kadi})   |   ⚖️ Güncel: {kilo} kg   |   📅 Aktif: {kayitli_gun} Gün"):
                
                if foto_b64:
                    pp_col, info_col = st.columns([1, 8])
                    pp_col.markdown(f'<img src="data:image/png;base64,{foto_b64}" class="custom-pp" style="width:100%; border-radius:10px;">', unsafe_allow_html=True)
                
                tab_detay, tab_ayar = st.tabs(["📊 Gelişmiş İstatistikler", "⚙️ Hesap Ayarları & İşlemler"])
                
                with tab_detay:
                    d_c1, d_c2, d_c3, d_c4 = st.columns(4)
                    d_c1.metric("Kayıt Tarihi", kayit_tarihi)
                    d_c2.metric("Cinsiyet / Boy", f"{cinsiyet[:1]} - {boy} cm")
                    d_c3.metric("Başlangıç Kilosu", f"{baslangic} kg")
                    d_c4.metric("Güncel VKİ", f"{vki:.1f}")
                    
                    st.write("")
                    d_c5, d_c6, d_c7, d_c8 = st.columns(4)
                    d_c5.metric("Hedef Kilo", f"{hedef} kg")
                    d_c6.metric("Verilen Kilo", f"{verilen:.1f} kg", delta=f"{-verilen:.1f} kg" if verilen > 0 else "0", delta_color="inverse")
                    
                    if (baslangic - hedef) > 0:
                        oran = max(0.0, min(verilen / (baslangic - hedef), 1.0))
                        st.progress(gorsel_ilerleme(oran), text=f"Hedefe Ulaşma Oranı: %{oran * 100:.7f}")

                with tab_ayar:
                    a_c1, a_c2 = st.columns(2)
                    
                    with a_c1:
                        st.markdown("**🔐 Şifre Değiştir**")
                        yeni_sifre = st.text_input("Kullanıcının Yeni Şifresi", value=sifre_text, key=f"sif_{kadi}")
                        if st.button("Şifreyi Güncelle", key=f"btn_sif_{kadi}", use_container_width=True):
                            db_firestore.collection("hesaplar").document(kadi).update({"sifre": yeni_sifre})
                            st.success("Şifre başarıyla güncellendi!")
                            st.rerun()
                            
                    with a_c2:
                        st.markdown("**🏷️ Kullanıcı Adı Değiştir**")
                        yeni_kadi = st.text_input("Yeni Kullanıcı Adı", value=kadi, key=f"kad_{kadi}")
                        if st.button("Kullanıcı Adını Değiştir", key=f"btn_kad_{kadi}", use_container_width=True):
                            if yeni_kadi == kadi:
                                st.warning("Mevcut kullanıcı adını girdiniz.")
                            elif " " in yeni_kadi:
                                st.error("Kullanıcı adında boşluk olamaz!")
                            else:
                                hedef_ref = db_firestore.collection("hesaplar").document(yeni_kadi)
                                if hedef_ref.get().exists:
                                    st.error("Bu kullanıcı adı başka biri tarafından kullanılıyor!")
                                else:
                                    eski_hesap_veri = hesap.to_dict()
                                    eski_hesap_veri["sifre"] = yeni_sifre
                                    
                                    db_firestore.collection("hesaplar").document(yeni_kadi).set(eski_hesap_veri)
                                    db_firestore.collection("kullanici_verileri").document(yeni_kadi).set(u_data)
                                    
                                    db_firestore.collection("hesaplar").document(kadi).delete()
                                    db_firestore.collection("kullanici_verileri").document(kadi).delete()
                                    
                                    st.success("Kullanıcı adı başarıyla değiştirildi ve veriler aktarıldı!")
                                    st.rerun()
                                    
                    st.divider()
                    if st.button("🔍 Kullanıcının Panelini İncele", key=f"view_{kadi}", type="primary", use_container_width=True):
                        st.session_state.incelenen_kullanici = kadi
                        st.session_state.panel_kapat = True
                        st.rerun()

        if bulunan_sayisi == 0:
            st.info("Arama kriterlerinize uyan bir kullanıcı bulunamadı.")

    # ---------------------------------------------------------
    # 3.2. KULLANICI (VEYA İNCELEME YAPAN ADMIN) GÖRÜNÜMÜ
    # ---------------------------------------------------------
    else:
        if kullanici_adi == "admin":
            kullanici_adi = st.session_state.incelenen_kullanici
            is_admin_viewing = True

        doc_ref = db_firestore.collection("kullanici_verileri").document(kullanici_adi)

        def verileri_yukle_bulut():
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            else:
                bugun = str(datetime.date.today())
                varsayilan = {
                    "profil": {"isim": "Ali Kaan Tüfekçi" if kullanici_adi == "ruthanly" else kullanici_adi, "kayit_tarihi": bugun}, 
                    "gecmis": {}
                }
                doc_ref.set(varsayilan)
                return varsayilan

        def verileri_kaydet_bulut(data):
            if not is_admin_viewing:
                doc_ref.set(data)

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

        # Temel Değişkenler ve Hesaplamalar
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

        # --- YAN MENÜ (SIDEBAR) ---
        with st.sidebar:
            if is_admin_viewing:
                if st.button("⬅️ Admin Paneline Dön", type="primary", use_container_width=True):
                    st.session_state.incelenen_kullanici = None
                    st.session_state.panel_kapat = True
                    st.rerun()
                st.write("---")

            foto_b64_user = p.get("foto_base64", "")
            if foto_b64_user:
                st.markdown(f'<div style="text-align:center;"><img src="data:image/png;base64,{foto_b64_user}" class="custom-pp" style="width:120px; height:120px; border-radius:50%; object-fit:cover; border:3px solid #2ecc71;"></div>', unsafe_allow_html=True)
            
            st.markdown(f"<h3 style='text-align:center; margin-top:10px;'>{isim}</h3>", unsafe_allow_html=True)
            
            if not is_admin_viewing:
                col_y_1, col_y_2 = st.columns(2)
                if col_y_1.button("⚙️ Ayarlar", use_container_width=True): 
                    st.session_state.aktif_sayfa = "Hesap Ayarları"
                    st.session_state.panel_kapat = True
                    st.rerun()
                if col_y_2.button("🚪 Çıkış", use_container_width=True, type="primary"): 
                    st.session_state.aktif_kullanici = None
                    st.rerun()

            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
            
            def profil_kaydet(k, v_key):
                if not is_admin_viewing:
                    v = st.session_state[v_key]
                    db["profil"][k] = str(v) if isinstance(v, datetime.date) else v
                    if k == "kilo": db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
                    if k == "baslangic_kilo" and "son_kilo_guncelleme" not in db["profil"]:
                        db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
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
                c1.number_input("Başlangıç Kilosu (kg)", 30.0, 250.0, float(p.get("baslangic_kilo", 80.0)), step=0.5, key="w_bk", on_change=profil_kaydet, args=("baslangic_kilo", "w_bk"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_bk", use_container_width=True): profil_sil("baslangic_kilo"); st.rerun()

            # 10 Günlük Kilo Takibi Mantığı
            son_tarih_str = p.get("son_kilo_guncelleme", "")
            if not son_tarih_str:
                hesap_doc = db_firestore.collection("hesaplar").document(kullanici_adi).get()
                if hesap_doc.exists: son_tarih_str = hesap_doc.to_dict().get("kayit_tarihi", "")
                if not son_tarih_str: son_tarih_str = str(datetime.date.today())

            try:
                gun_farki = (datetime.date.today() - datetime.datetime.strptime(son_tarih_str, "%Y-%m-%d").date()).days
                kilo_acik = True if gun_farki >= 10 else False
            except: kilo_acik = False

            with st.expander("⚖️ Güncel Kilo Takibi", expanded=kilo_acik):
                if kilo_acik: st.warning("Kilonuzu güncelleme vaktiniz geldi!")
                st.markdown(f"<small style='color:gray;'>Başlangıç Kilonuz: <b>{baslangic} kg</b></small>", unsafe_allow_html=True)
                yeni_gkilo = st.number_input("Güncel Kilo (kg)", 30.0, 250.0, kilo, step=0.5, key="w_gk", disabled=is_admin_viewing)
                
                if not is_admin_viewing:
                    col_btn1, col_btn2 = st.columns(2)
                    if col_btn1.button("🔄 Sıfırla", use_container_width=True):
                        profil_sil("kilo"); profil_sil("son_kilo_guncelleme"); st.rerun()
                    if col_btn2.button("💾 Kaydet", use_container_width=True, type="primary"):
                        db["profil"]["kilo"] = yeni_gkilo
                        db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
                        doc_ref.set(db); st.success("Güncellendi!"); st.rerun()

            with st.expander("🎯 Hedeflerim", expanded=False):
                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Kilo (kg)", 30.0, 200.0, float(p.get("hedef_kilo", 70.0)), step=0.5, key="w_hk", on_change=profil_kaydet, args=("hedef_kilo", "w_hk"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_hk", use_container_width=True): profil_sil("hedef_kilo"); st.rerun()

                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Süre (Gün)", 1, 730, int(p.get("hedef_gun", 30)), key="w_hg", on_change=profil_kaydet, args=("hedef_gun", "w_hg"), disabled=is_admin_viewing)
                with c2:
                    hizala()
                    if not is_admin_viewing and st.button("🗑️", key="del_hg", use_container_width=True): profil_sil("hedef_gun"); st.rerun()

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
            toplam_acik_panel = sum(max(0, int(tdee) - (v.get("toplam", 0) - v.get("yakilan_kalori", 0))) for v in db["gecmis"].values() if v.get("toplam", 0) > 0)
            ilerleme_orani = max(0.0, min(toplam_acik_panel / hedef_toplam_acik, 1.0)) if hedef_toplam_acik > 0 else 0.0
            
            m_c1, m_c2 = st.columns(2)
            m_c1.metric("Verilen", f"{verilen_kilo:.1f} kg")
            m_c2.metric("Kalan", f"{toplam_verilecek:.1f} kg")
            st.progress(gorsel_ilerleme(ilerleme_orani), text=f"Hedefe Ulaşma: %{ilerleme_orani * 100:.7f}")

        # --- SAYFA İÇERİĞİ YÖNLENDİRMELER ---
        if is_admin_viewing:
            st.warning(f"👁️ ŞU AN İZLEME MODUNDASINIZ: Kullanıcı **{kullanici_adi}** paneli görüntüleniyor. Değiştirme butonları gizlenmiştir.")

        if st.session_state.aktif_sayfa == "Hesap Ayarları":
            if st.session_state.get("hesap_guncellendi_mesaji"):
                st.success(st.session_state.hesap_guncellendi_mesaji)
                st.warning("Güvenliğiniz için çıkış yapıldı. Lütfen yeni bilgilerinizle giriş yapın.")
                if st.button("Giriş Ekranına Dön", type="primary", use_container_width=True):
                    st.session_state.aktif_kullanici = None
                    st.session_state.hesap_guncellendi_mesaji = None
                    st.session_state.aktif_sayfa = "📅 Günlük Takip"
                    st.rerun()
                st.stop() 

            if st.button("⬅️ Ana Menüye Dön"): st.session_state.aktif_sayfa = "📅 Günlük Takip"; st.rerun()
            st.title("⚙️ Hesap Yönetimi")
            
            if is_admin_viewing: st.error("Admin olarak bu işlemi yapamazsınız.")
            else:
                tab_h1, tab_h2, tab_h3 = st.tabs(["📸 Fotoğraf", "🔐 Şifre", "🏷️ Kullanıcı Adı"])
                
                with tab_h1:
                    uploaded_pp = st.file_uploader("Profil Fotoğrafı Seç", type=["jpg", "png", "jpeg"])
                    if uploaded_pp and st.button("💾 Fotoğrafı Kaydet", use_container_width=True, type="primary"):
                        img = Image.open(uploaded_pp); img.thumbnail((250, 250))
                        buf = io.BytesIO(); img.save(buf, format="PNG")
                        db["profil"]["foto_base64"] = base64.b64encode(buf.getvalue()).decode()
                        doc_ref.set(db); st.success("Güncellendi!"); st.rerun()
                    if f_b64 and st.button("🗑️ Mevcut Fotoğrafı Kaldır", use_container_width=True):
                        del db["profil"]["foto_base64"]; doc_ref.set(db); st.rerun()

                with tab_h2:
                    s1 = st.text_input("Mevcut Şifre", type="password")
                    s2 = st.text_input("Yeni Şifre", type="password")
                    s3 = st.text_input("Yeni Şifre (Tekrar)", type="password")
                    if st.button("🔐 Şifremi Güncelle", use_container_width=True):
                        g_sif = db_firestore.collection("hesaplar").document(kullanici_adi).get().to_dict().get("sifre", "")
                        if s1 != g_sif: st.error("Mevcut şifre yanlış!")
                        elif not s2 or s2 != s3: st.error("Yeni şifreler eşleşmiyor veya boş!")
                        else:
                            db_firestore.collection("hesaplar").document(kullanici_adi).update({"sifre": s2})
                            st.session_state.hesap_guncellendi_mesaji = "Şifreniz değiştirildi!"; st.rerun()

                with tab_h3:
                    k1 = st.text_input("Mevcut Kullanıcı Adı").strip().lower()
                    k2 = st.text_input("Yeni Kullanıcı Adı").strip().lower()
                    k3 = st.text_input("Yeni Kullanıcı Adı (Tekrar)").strip().lower()
                    if st.button("🏷️ Kullanıcı Adımı Güncelle", use_container_width=True):
                        if k1 != kullanici_adi: st.error("Mevcut kullanıcı adı yanlış!")
                        elif " " in k2 or not k2: st.error("Hatalı veya boş yeni kullanıcı adı!")
                        elif k2 != k3: st.error("Yeni adlar eşleşmiyor!")
                        elif db_firestore.collection("hesaplar").document(k2).get().exists: st.error("Bu isim alınmış!")
                        else:
                            e_veri = db_firestore.collection("hesaplar").document(kullanici_adi).get().to_dict()
                            db_firestore.collection("hesaplar").document(k2).set(e_veri)
                            db_firestore.collection("kullanici_verileri").document(k2).set(db)
                            db_firestore.collection("hesaplar").document(kullanici_adi).delete()
                            db_firestore.collection("kullanici_verileri").document(kullanici_adi).delete()
                            st.session_state.hesap_guncellendi_mesaji = "Kullanıcı adınız değiştirildi!"; st.rerun()

        else:
            st.radio("Menü:", ["📅 Günlük Takip", "🤖 Koçluk Merkezi"], key="aktif_sayfa", horizontal=True, label_visibility="collapsed")
            
            if st.session_state.aktif_sayfa == "📅 Günlük Takip":
                if 'secili_tarih' not in st.session_state: st.session_state.secili_tarih = datetime.date.today()

                # --- TARİH KUTUSU ---
                with st.container(border=True):
                    col_b1, col_t, col_b2, col_b3 = st.columns([1.2, 2, 1.2, 1.2])
                    with col_b1:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button("◀ Önce", use_container_width=True): st.session_state.secili_tarih -= datetime.timedelta(days=1); st.rerun()
                    with col_t:
                        st.session_state.secili_tarih = st.date_input("Çalışılan Tarih:", value=st.session_state.secili_tarih, max_value=datetime.date.today())
                        islem_tarihi = str(st.session_state.secili_tarih)
                    with col_b2:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.session_state.secili_tarih < datetime.date.today():
                            if st.button("🎯 Bugün", type="primary", use_container_width=True): st.session_state.secili_tarih = datetime.date.today(); st.rerun()
                    with col_b3:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.session_state.secili_tarih < datetime.date.today():
                            if st.button("Sonra ▶", use_container_width=True): st.session_state.secili_tarih += datetime.timedelta(days=1); st.rerun()

                if islem_tarihi not in db["gecmis"]: 
                    db["gecmis"][islem_tarihi] = {"toplam": 0, "toplam_p": 0, "toplam_c": 0, "toplam_y": 0, "ogünler": [], "su_litre": 0.0, "egzersizler": [], "yakilan_kalori": 0}
                    db["gecmis"][islem_tarihi]["su_hedef"] = hedef_su_litre
                    verileri_kaydet_bulut(db)

                # Dünkü Kaçamak Hesabı
                dun_str = str(st.session_state.secili_tarih - datetime.timedelta(days=1))
                gunluk_limit = orijinal_gunluk_limit 
                
                if dun_str in db["gecmis"]:
                    dun_v = db["gecmis"][dun_str]
                    dun_su, dun_hedef_su = dun_v.get("su_litre", 0), dun_v.get("su_hedef", 2.5)
                    if dun_su < dun_hedef_su:
                        st.warning(f"💧 **Dünkü Su Eksikliği:** Hedeflenen suyu tamamlayamadın ({dun_su}L / {dun_hedef_su}L).")
                    
                    dun_net = max(0, dun_v.get("toplam", 0) - dun_v.get("yakilan_kalori", 0))
                    if dun_v.get("toplam", 0) > 0: 
                        fark = dun_net - orijinal_gunluk_limit
                        if fark > 0:
                            telafi = fark // 3
                            gunluk_limit = orijinal_gunluk_limit - telafi 
                            st.warning(f"⚖️ **Dünkü Kaçamak:** Hedefini **{fark} kcal** aştın. Bugünkü hedeften **{telafi} kcal** kısıldı.")
                        elif fark <= 0:
                            st.success(f"🎉 **Harika İş Çıkardın:** Dün hedefine tam sadık kaldın ve fazladan açık yarattın!")

                # --- UX MİMARİSİ: ALT SEKMELER (TABS) ---
                tab_ekle, tab_ozet, tab_egzersiz = st.tabs(["🍽️ Yiyecek Ekle & Menü", "📊 Günlük Özet & Su", "🏃 Egzersiz"])

                # ===============================================
                # TAB 1: YİYECEK EKLE & MENÜ
                # ===============================================
                with tab_ekle:
                    if not is_admin_viewing:
                        with st.container(border=True):
                            st.markdown(f"#### 🍽️ Yiyecek Ekle")

                            if 'tabak_listesi' not in st.session_state: st.session_state.tabak_listesi = []
                            if 'onay_bekleyen_metin' not in st.session_state: st.session_state.onay_bekleyen_metin = None
                            if 'kaydedilecek_ogun_tipi' not in st.session_state: st.session_state.kaydedilecek_ogun_tipi = "Öğün"
                            if 'json_veri' not in st.session_state: st.session_state.json_veri = []

                            if st.session_state.onay_bekleyen_metin:
                                st.warning(f"🤖 AI {st.session_state.kaydedilecek_ogun_tipi} makrolarını hesapladı. Onaylıyor musun?")
                                st.info(st.session_state.onay_bekleyen_metin.replace('\n', '\n\n'))
                                c_evet, c_hayir = st.columns(2)
                                
                                if c_evet.button("✅ Evet (Tabağa Ekle)", use_container_width=True, type="primary"):
                                    yeni_ogun = {
                                        "tip": st.session_state.kaydedilecek_ogun_tipi, 
                                        "kalemler": st.session_state.json_veri, 
                                        "toplam_kalori": sum(x.get('kalori',0) for x in st.session_state.json_veri),
                                        "toplam_p": sum(x.get('p',0) for x in st.session_state.json_veri),
                                        "toplam_c": sum(x.get('c',0) for x in st.session_state.json_veri),
                                        "toplam_y": sum(x.get('y',0) for x in st.session_state.json_veri)
                                    }
                                    db["gecmis"][islem_tarihi]["ogünler"].append(yeni_ogun)
                                    gunluk_toplam_guncelle(islem_tarihi) 
                                    st.session_state.tabak_listesi = []; st.session_state.onay_bekleyen_metin = None; st.session_state.json_veri = []; st.rerun()
                                    
                                if c_hayir.button("❌ Hayır (İptal)", use_container_width=True):
                                    st.session_state.onay_bekleyen_metin = None; st.session_state.json_veri = []; st.rerun()

                            else:
                                t_liste, t_foto, t_manuel = st.tabs(["📝 Liste", "📸 Fotoğraf", "✍️ Manuel"])

                                with t_liste:
                                    ogun_tipi = st.selectbox("Öğün Türü", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün", "Atıştırmalık"], label_visibility="collapsed")
                                    sec_ymk = st.selectbox("Arayın veya Seçin:", ["✍️ Listede Yok, Kendim Yazacağım"] + sorted(YAYGIN_YEMEKLER))
                                    y_adi = st.text_input("Ne yedin?", placeholder="Örn: Ev yapımı kek", label_visibility="collapsed") if sec_ymk == "✍️ Listede Yok, Kendim Yazacağım" else sec_ymk
                                    
                                    b_sozlugu = {"çorba": ["kase", "kepçe"], "su": ["bardak", "şişe"], "ekmek": ["dilim"], "pilav": ["porsiyon", "kaşık"], "et": ["gram", "porsiyon"]}
                                    a_birimler = ["porsiyon", "adet", "dilim", "kase", "bardak", "gram", "yemek kaşığı", "avuç", "kepçe", "bütün"]
                                    if y_adi:
                                        for k, bl in b_sozlugu.items():
                                            if k in y_adi.lower(): a_birimler = bl + [b for b in a_birimler if b not in bl]; break 
                                    
                                    cm, cb = st.columns(2)
                                    ymk_mik = cm.number_input("Miktar", 0.01, 1000.0, 1.0, 0.5)
                                    ymk_brm = cb.selectbox("Birim", a_birimler)
                                    
                                    if st.button("➕ Tabağa Ekle", use_container_width=True) and y_adi:
                                        st.session_state.tabak_listesi.append(f"{ymk_mik} {ymk_brm} {y_adi}"); st.rerun()

                                    if st.session_state.tabak_listesi:
                                        st.divider()
                                        for i, elm in enumerate(st.session_state.tabak_listesi):
                                            c_y, c_s = st.columns([6, 1])
                                            c_y.markdown(f"🍽️ {elm}")
                                            if c_s.button("❌", key=f"s_tbk_{i}"): st.session_state.tabak_listesi.pop(i); st.rerun()
                                                
                                        if st.button("🚀 Tabağı İncele ve Hesapla", type="primary", use_container_width=True):
                                            st.session_state.kaydedilecek_ogun_tipi = ogun_tipi
                                            with st.spinner("AI hesaplıyor..."):
                                                # KESİN VE NET ŞABLON PROMPTU
                                                prompt = f"""Kullanıcı yediği menü: {", ".join(st.session_state.tabak_listesi)}. 
                                                Bu yiyeceklerin kalori, Protein(p), Karb(c) ve Yağ(y) değerlerini hesapla.
                                                YANITINI SADECE VE SADECE AŞAĞIDAKİ GİBİ BİR JSON DİZİSİ OLARAK VER. BAŞKA HİÇBİR ŞEY YAZMA:
                                                [
                                                  {{"ad": "1 Porsiyon Pilav", "kalori": 250, "p": 5, "c": 40, "y": 5}}
                                                ]"""
                                                try:
                                                    res = model.generate_content(prompt)
                                                    v_list = json_kurtar(res.text)
                                                    
                                                    metin = ""
                                                    for item in v_list: metin += f"- {item.get('ad','Bilinmeyen')}: **{item.get('kalori',0)} kcal** | {item.get('p',0)}P | {item.get('c',0)}K | {item.get('y',0)}Y\n"
                                                    metin += f"\n**TOPLAM: {sum(x.get('kalori',0) for x in v_list)} kcal**"
                                                    
                                                    st.session_state.json_veri = v_list
                                                    st.session_state.onay_bekleyen_metin = metin
                                                    st.rerun()
                                                except Exception as e: st.error(f"Sistem Hatası: {e}")

                                with t_foto:
                                    st.info("📸 Fotoğrafı yükle, gerisini AI halletsin!")
                                    foto_ogun = st.selectbox("Öğün Seç", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün", "Atıştırmalık"])
                                    yuklenen = st.file_uploader("Fotoğraf Seç", type=["jpg", "jpeg", "png"])
                                    ipucu = st.text_input("💡 Yemeğin ne olduğunu biliyor musun?", placeholder="Örn: Fırın makarna")
                                    
                                    if yuklenen:
                                        img = Image.open(yuklenen)
                                        st.image(img, use_container_width=True)
                                        if st.button("🚀 Analiz Et ve Hesapla", type="primary", use_container_width=True):
                                            st.session_state.kaydedilecek_ogun_tipi = foto_ogun
                                            with st.spinner("AI fotoğrafa bakıyor..."):
                                                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                                                ek_b = f"Bu yemeğin '{ipucu}' olduğu belirtildi. " if ipucu else ""
                                                
                                                # KESİN VE NET FOTOĞRAF PROMPTU
                                                prompt = f"""{ek_b}Fotoğraftaki yiyecekleri tespit et, porsiyon tahmini yap ve kalori, p, c, y değerlerini hesapla.
                                                YANITINI SADECE VE SADECE AŞAĞIDAKİ GİBİ BİR JSON DİZİSİ OLARAK VER. BAŞKA HİÇBİR ŞEY YAZMA:
                                                [
                                                  {{"ad": "1 Porsiyon Pilav", "kalori": 250, "p": 5, "c": 40, "y": 5}}
                                                ]"""
                                                try:
                                                    res = model.generate_content([prompt, img])
                                                    v_list = json_kurtar(res.text)
                                                    
                                                    metin = ""
                                                    for item in v_list: metin += f"- {item.get('ad','Bilinmeyen')}: **{item.get('kalori',0)} kcal** | {item.get('p',0)}P | {item.get('c',0)}K | {item.get('y',0)}Y\n"
                                                    metin += f"\n**TOPLAM: {sum(x.get('kalori',0) for x in v_list)} kcal**"
                                                    
                                                    st.session_state.json_veri = v_list
                                                    st.session_state.onay_bekleyen_metin = metin
                                                    st.rerun()
                                                except Exception as e: st.error(f"Görsel Analiz Hatası: {e}")
                                    
                                with t_manuel:
                                    m_ogun = st.selectbox("Öğün", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün"])
                                    m_ad = st.text_input("Yemek Adı")
                                    c1, c2, c3, c4 = st.columns(4)
                                    m_k = c1.number_input("Kcal", 0, 5000, 100)
                                    m_p = c2.number_input("P(g)", 0, 500, 0)
                                    m_c = c3.number_input("Karb", 0, 500, 0)
                                    m_y = c4.number_input("Yağ", 0, 500, 0)
                                    
                                    if st.button("Listeye Ekle", use_container_width=True) and m_ad:
                                        yeni_ogun = {
                                            "tip": m_ogun, "kalemler": [{"ad": m_ad, "kalori": m_k, "p":m_p, "c":m_c, "y":m_y}], 
                                            "toplam_kalori": m_k, "toplam_p": m_p, "toplam_c": m_c, "toplam_y": m_y
                                        }
                                        db["gecmis"][islem_tarihi]["ogünler"].append(yeni_ogun)
                                        gunluk_toplam_guncelle(islem_tarihi); st.rerun()

                    with st.container(border=True):
                        st.markdown(f"### 📋 Bugünkü Menü")
                        gunluk_veri = db["gecmis"][islem_tarihi]
                        if not gunluk_veri["ogünler"]: st.info("Bu tarihte henüz bir şey yemedin. 🍽️")
                        else:
                            for m_idx, ogun in enumerate(gunluk_veri["ogünler"]):
                                with st.container(border=True):
                                    c_bas, c_sil = st.columns([4, 1])
                                    c_bas.markdown(f"#### 🥘 {ogun['tip']} ({ogun.get('toplam_kalori', 0)} kcal)")
                                    if not is_admin_viewing and c_sil.button("🗑️ Sil", key=f"d_o_{m_idx}"):
                                        gunluk_veri["ogünler"].pop(m_idx); gunluk_toplam_guncelle(islem_tarihi); st.rerun()
                                        
                                    for k_idx, kalem in enumerate(ogun.get("kalemler", [])):
                                        ci, ck, cmk, csi = st.columns([4, 2, 3, 1])
                                        ci.write(f"🔹 {kalem['ad']}"); ck.write(f"**{kalem['kalori']} kcal**")
                                        cmk.caption(f"{kalem.get('p',0)}P | {kalem.get('c',0)}K | {kalem.get('y',0)}Y")
                                        if not is_admin_viewing and csi.button("❌", key=f"d_i_{m_idx}_{k_idx}"):
                                            ogun["toplam_kalori"] -= kalem["kalori"]
                                            ogun["toplam_p"] -= kalem.get("p",0); ogun["toplam_c"] -= kalem.get("c",0); ogun["toplam_y"] -= kalem.get("y",0)
                                            ogun["kalemler"].pop(k_idx)
                                            if len(ogun["kalemler"]) == 0: gunluk_veri["ogünler"].pop(m_idx)
                                            gunluk_toplam_guncelle(islem_tarihi); st.rerun()

                # ===============================================
                # TAB 2: ÖZET & SU
                # ===============================================
                with tab_ozet:
                    with st.container(border=True):
                        col_ozet, col_su = st.columns([3, 2])
                        with col_ozet:
                            st.markdown(f"#### 📊 {islem_tarihi} Özeti")
                            alinan_k = db["gecmis"][islem_tarihi].get("toplam", 0)
                            yakilan_k = db["gecmis"][islem_tarihi].get("yakilan_kalori", 0)
                            net_kalori = max(0, alinan_k - yakilan_k)
                            kalan_k = max(0, gunluk_limit - net_kalori)

                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("🔥 Alınan", f"{alinan_k}")
                            c2.metric("🏃 Yakılan", f"{yakilan_k}")
                            c3.metric("🎯 Hedef", f"{gunluk_limit}")
                            c4.metric("✅ Kalan", f"{kalan_k}", delta=f"{kalan_k} kcal" if kalan_k > 0 else "Sınır Aşıldı!", delta_color="normal" if kalan_k > 0 else "inverse")
                            st.progress(min(net_kalori / gunluk_limit if gunluk_limit > 0 else 0, 1.0))

                            st.markdown("##### 🥩 Makrolar")
                            m1, m2, m3 = st.columns(3)
                            ap, ac, ay = db["gecmis"][islem_tarihi].get("toplam_p", 0), db["gecmis"][islem_tarihi].get("toplam_c", 0), db["gecmis"][islem_tarihi].get("toplam_y", 0)
                            
                            m1.markdown(f"**Protein:** {ap}g / {hedef_protein}g")
                            m1.progress(min(ap / hedef_protein if hedef_protein > 0 else 0, 1.0))
                            m2.markdown(f"**Karb:** {ac}g / {hedef_karb}g")
                            m2.progress(min(ac / hedef_karb if hedef_karb > 0 else 0, 1.0))
                            m3.markdown(f"**Yağ:** {ay}g / {hedef_yag}g")
                            m3.progress(min(ay / hedef_yag if hedef_yag > 0 else 0, 1.0))

                        with col_su:
                            st.markdown("#### 💧 Su Takibi")
                            m_su = db["gecmis"][islem_tarihi].get("su_litre", 0.0)
                            st.metric("İçilen Su", f"{m_su:.2f} L", f"Hedef: {hedef_su_litre} L", delta_color="off")
                            st.progress(min(m_su / hedef_su_litre if hedef_su_litre > 0 else 0, 1.0))
                            st.write("") 
                            if not is_admin_viewing:
                                bs1, bs2, bs3 = st.columns(3)
                                if bs1.button("🥛 +200ml", use_container_width=True): db["gecmis"][islem_tarihi]["su_litre"] = round(m_su + 0.2, 2); doc_ref.set(db); st.rerun()
                                if bs2.button("🍼 +500ml", use_container_width=True): db["gecmis"][islem_tarihi]["su_litre"] = round(m_su + 0.5, 2); doc_ref.set(db); st.rerun()
                                if bs3.button("🔄 Sıfırla", use_container_width=True): db["gecmis"][islem_tarihi]["su_litre"] = 0.0; doc_ref.set(db); st.rerun()

                    with st.container(border=True):
                        st.markdown("### 🍩 Dağılım Grafikleri")
                        cg1, cg2 = st.columns(2)
                        
                        o_top, gp, gc, gy = {}, 0, 0, 0
                        for o in db["gecmis"][islem_tarihi]["ogünler"]:
                            o_top[o["tip"]] = o_top.get(o["tip"], 0) + o.get("toplam_kalori", 0)
                            gp += o.get("toplam_p", 0); gc += o.get("toplam_c", 0); gy += o.get("toplam_y", 0)

                        with cg1:
                            st.markdown("<h5 style='text-align:center;'>Öğün Kalorileri</h5>", unsafe_allow_html=True)
                            if o_top and sum(o_top.values()) > 0:
                                if GRAFIK_AKTIF:
                                    fig_kal = px.pie(pd.DataFrame(list(o_top.items()), columns=["Öğün", "Kcal"]), values="Kcal", names="Öğün", hole=0.4, color_discrete_sequence=px.colors.sequential.Teal)
                                    fig_kal.update_traces(textposition='inside', textinfo='percent+label'); fig_kal.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=300)
                                    st.plotly_chart(fig_kal, use_container_width=True)
                                else:
                                    for o_ad, kal in o_top.items(): st.caption(f"**{o_ad}** - {kal} kcal"); st.progress(kal/sum(o_top.values()))
                            else: st.info("Henüz veri yok.")

                        with cg2:
                            st.markdown("<h5 style='text-align:center;'>Makrolar</h5>", unsafe_allow_html=True)
                            if gp+gc+gy > 0:
                                if GRAFIK_AKTIF:
                                    fig_mak = px.pie(pd.DataFrame([{"M":"Protein","G":gp},{"M":"Karb","G":gc},{"M":"Yağ","G":gy}]), values="G", names="M", hole=0.4, color="M", color_discrete_map={"Protein":"#e74c3c","Karb":"#f1c40f","Yağ":"#3498db"})
                                    fig_mak.update_traces(textposition='inside', textinfo='percent+label'); fig_mak.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=300)
                                    st.plotly_chart(fig_mak, use_container_width=True)
                                else:
                                    st.caption(f"P: {gp}g"); st.progress(gp/(gp+gc+gy))
                                    st.caption(f"C: {gc}g"); st.progress(gc/(gp+gc+gy))
                                    st.caption(f"Y: {gy}g"); st.progress(gy/(gp+gc+gy))
                            else: st.info("Henüz veri yok.")

                # ===============================================
                # TAB 3: EGZERSİZ
                # ===============================================
                with tab_egzersiz:
                    with st.container(border=True):
                        st.markdown("### 🏃 Egzersiz")
                        if not db["gecmis"][islem_tarihi].get("egzersizler"): st.info("Bugün henüz egzersiz girmedin.")
                        else:
                            for e_idx, ex in enumerate(db["gecmis"][islem_tarihi]["egzersizler"]):
                                ce1, ce2, ce3 = st.columns([6, 2, 1])
                                ce1.write(f"🏋️ {ex['ad']} ({ex['sure']} dk)"); ce2.write(f"**🔥 {ex['kalori']} kcal**")
                                if not is_admin_viewing and ce3.button("❌", key=f"dx_{e_idx}"):
                                    db["gecmis"][islem_tarihi]["yakilan_kalori"] -= ex["kalori"]
                                    db["gecmis"][islem_tarihi]["egzersizler"].pop(e_idx); doc_ref.set(db); st.rerun()

                        if not is_admin_viewing:
                            st.markdown("#### ➕ Yeni Ekle")
                            te1, te2 = st.tabs(["🤖 AI Hesapla", "✍️ Manuel"])
                            with te1:
                                x_sec = st.selectbox("Tür:", ["Yürüyüş", "Koşu", "Bisiklet", "Ağırlık", "Diğer (Yazacağım)"])
                                x_ad = st.text_input("Ne yaptınız?") if x_sec == "Diğer (Yazacağım)" else x_sec
                                x_sure = st.number_input("Süre (Dk):", 1, 600, 30)
                                if st.button("🔥 Ekle", use_container_width=True) and x_ad:
                                    with st.spinner("Hesaplanıyor..."):
                                        try:
                                            r = model.generate_content(f"Kullanıcı: {kilo}kg,{boy}cm,{yas}yaş. Yaptığı: {x_sure}dk {x_ad}. SADECE YAKILAN KALORİYİ TAM SAYI VER.")
                                            kb = int(re.search(r'\d+', r.text).group())
                                            db["gecmis"][islem_tarihi]["egzersizler"].append({"ad": x_ad, "sure": x_sure, "kalori": kb})
                                            db["gecmis"][islem_tarihi]["yakilan_kalori"] += kb; doc_ref.set(db); st.rerun()
                                        except: st.error("Hesaplama başarısız.")
                            with te2:
                                cm1, cm2 = st.columns([3, 1])
                                mx_ad = cm1.text_input("Adı:", placeholder="Yoga")
                                mx_kal = cm2.number_input("Kcal:", 1, 5000, 100)
                                if st.button("Ekle", key="bmx") and mx_ad:
                                    db["gecmis"][islem_tarihi]["egzersizler"].append({"ad": mx_ad, "sure": "Manuel", "kalori": mx_kal})
                                    db["gecmis"][islem_tarihi]["yakilan_kalori"] += mx_kal; doc_ref.set(db); st.rerun()

            # ==========================================
            # 4. KOÇLUK MERKEZİ SAYFASI
            # ==========================================
            elif st.session_state.aktif_sayfa == "🤖 Koçluk Merkezi":
                t_acik, t_gun = 0, 0
                for v in db["gecmis"].values():
                    net = v.get("toplam", 0) - v.get("yakilan_kalori", 0)
                    if v.get("toplam", 0) > 0: t_acik += int(tdee) - net; t_gun += 1
                        
                vki = kilo / ((boy / 100) ** 2) if boy > 0 else 0
                if vki < 18.5: drm, rnk, a_snr = "Zayıf", "#e74c3c", 0
                elif 18.5 <= vki < 24.9: drm, rnk, a_snr = "Normal", "#2ecc71", 0
                elif 25 <= vki < 29.9: drm, rnk, a_snr = "Fazla Kilolu", "#f1c40f", 24.9 * ((boy/100)**2)
                else: drm, rnk, a_snr = "Obez", "#e67e22", 29.9 * ((boy/100)**2)

                with st.container(border=True):
                    cy1, cy2 = st.columns([3, 1])
                    cy1.markdown("### 💬 Yapay Zeka Uzman Diyetisyen")
                    cy1.caption("Tüm vücut verilerini ve geçmişini analiz edip özel rapor hazırlar.")
                    if not is_admin_viewing and cy2.button("🤖 Değerlendir", use_container_width=True, type="primary"):
                        with st.spinner("İnceleniyor..."):
                            try:
                                r = model.generate_content(f"Kullanıcı {isim}. Boy:{boy}cm, Kilo:{kilo}kg (Başlangıç:{baslangic}kg), Hedef:{hedef_kilo}kg. VKİ:{vki:.1f}. Değerlendir ve samimi bir tavsiye ver.")
                                st.success("✅ Rapor Hazır"); st.write(r.text)
                            except: st.error("Hata oluştu.")
                                
                with st.container(border=True):
                    st.markdown("### 🏆 Detaylı Başarı Dashboard'u")
                    cm1, cm2, cm3, cm4 = st.columns(4)
                    cm1.metric("Verilen Kilo", f"{verilen_kilo:.1f} kg", f"{baslangic} kg'dan", delta_color="off")
                    cm2.metric("Yakılan Yağ", f"{t_acik/7700 if t_acik>0 else 0:.2f} kg", "Tahmini", delta_color="off")
                    cm3.metric("Kayıtlı Gün", f"{t_gun} Gün", delta_color="off")
                    cm4.metric("Ortalama Açık", f"{int(t_acik/t_gun) if t_gun>0 else 0} kcal", "Gün/Ort", delta_color="off")
                    
                    i_oran = max(0.0, min(t_acik / hedef_toplam_acik, 1.0)) if hedef_toplam_acik > 0 else 0.0
                    st.progress(gorsel_ilerleme(i_oran), text=f"Hedefe Ulaşma Oranı: %{i_oran * 100:.7f}")
                
                with st.container(border=True):
                    st.markdown(f"### 🩺 VKİ Analizi: `{vki:.1f}` 👉 <span style='color:{rnk}; font-weight:bold;'>{drm}</span>", unsafe_allow_html=True)
                    st.write(f"Sağlıklı aralık: **{18.5*((boy/100)**2):.1f} kg - {24.9*((boy/100)**2):.1f} kg**")
                    if a_snr > 0: st.info(f"💡 Bir alt gruba düşmek için vermeniz gereken asgari kilo: **{kilo - a_snr:.1f} kg**")

                with st.container(border=True):
                    if t_gun > 3 and verilen_kilo > 0:
                        hiz = verilen_kilo / t_gun
                        kgun = int(toplam_verilecek / hiz) if hiz > 0 else 0
                        st.success(f"🚀 Hızınız: **{hiz:.2f} kg/gün**. Hedefe kalan süre: **{kgun} gün ({(datetime.date.today() + datetime.timedelta(days=kgun)).strftime('%d.%m.%Y')})**")
                    else: st.info("Hız tahmini için daha fazla düzenli gün girişine ihtiyaç var.")

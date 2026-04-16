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
import ast

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
# YARDIMCI FONKSİYONLAR (ZIRHLI JSON)
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

def guvenli_json_oku(metin):
    """Yapay zekadan gelen veriyi ASLA ÇÖKMEYECEK şekilde okur."""
    try:
        # Önce doğrudan okumayı dener
        return json.loads(metin)
    except:
        pass

    try:
        # Markdown işaretlerini ve dışarıdaki yazıları temizle
        temiz = re.sub(r'```json\s*|```\s*', '', metin)
        match = re.search(r'(\[.*\]|\{.*\})', temiz, re.DOTALL)
        if match:
            temiz = match.group(1)
        
        # Enter ve tab hatalarını sil
        temiz = temiz.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
        veri = json.loads(temiz)
        
        # Obje geldiyse diziye çevir
        if isinstance(veri, dict):
            for k, v in veri.items():
                if isinstance(v, list): return v
            return [veri]
        return veri
    except:
        try:
            # En son çare (Yedek Paraşüt): Python AST ile okuma
            veri = ast.literal_eval(temiz)
            if isinstance(veri, dict):
                for k, v in veri.items():
                    if isinstance(v, list): return v
                return [veri]
            return veri
        except:
            # Hiçbiri olmazsa sistemi çökertmek yerine sahte hata verisi döner
            return [{"ad": "⚠️ Anlaşılamadı (Manuel Ekleyin)", "kalori": 0, "p": 0, "c": 0, "y": 0}]

def gorsel_ilerleme(gercek_oran):
    if gercek_oran <= 0: return 0.0
    return max(0.05, min(gercek_oran, 1.0))

# ==========================================
# 1. YAPAY ZEKA VE VERİ LİSTELERİ
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)

# Detaylı ve hatasız düşünmesi için token limiti yüksek, sıcaklık düşük
generation_config = genai.GenerationConfig(
    max_output_tokens=2500, 
    temperature=0.1
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
                k_id = "admin" if giris_kadi == "admin" else giris_kadi
                kullanici_doc = db_firestore.collection("hesaplar").document(k_id).get()
                if not kullanici_doc.exists and k_id == "admin":
                    db_firestore.collection("hesaplar").document("admin").set({"sifre": giris_sifre, "kayit_tarihi": str(datetime.date.today())})
                    st.session_state.aktif_kullanici = "admin"; st.rerun()
                elif kullanici_doc.exists and kullanici_doc.to_dict().get("sifre") == giris_sifre:
                    st.session_state.aktif_kullanici = k_id; st.rerun()
                else: st.error("Kullanıcı adı veya şifre hatalı!")
                    
        with tab_kayit:
            kayit_kadi = st.text_input("Yeni Kullanıcı Adı", key="reg_kadi").strip().lower()
            kayit_sifre = st.text_input("Yeni Şifre", type="password", key="reg_sifre")
            kayit_sifre_tekrar = st.text_input("Şifreyi Tekrar Girin", type="password", key="reg_sifre2")
            if st.button("Kayıt Ol", use_container_width=True):
                if not kayit_kadi or not kayit_sifre: st.warning("Alanları doldurun.")
                elif " " in kayit_kadi: st.error("Kullanıcı adında boşluk olamaz!")
                elif kayit_sifre != kayit_sifre_tekrar: st.error("Şifreler eşleşmiyor!")
                elif db_firestore.collection("hesaplar").document(kayit_kadi).get().exists: st.error("Bu kullanıcı adı alınmış!")
                else:
                    bugun = str(datetime.date.today())
                    db_firestore.collection("hesaplar").document(kayit_kadi).set({"sifre": kayit_sifre, "kayit_tarihi": bugun})
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
                st.session_state.aktif_kullanici = None; st.rerun()

        st.markdown("<h2 style='text-align: center; color: #e74c3c;'>👑 Yönetici Paneli</h2>", unsafe_allow_html=True)
        st.divider()
        arama_metni = st.text_input("🔍 Kullanıcı Ara", placeholder="Örn: ali veya ruthanly").strip().lower()
        st.write("")

        hesaplar = db_firestore.collection("hesaplar").stream()
        for hesap in hesaplar:
            kadi = hesap.id
            if kadi == "admin": continue
                
            veri_doc = db_firestore.collection("kullanici_verileri").document(kadi).get()
            u_data = veri_doc.to_dict() if veri_doc.exists else {}
            profil, gecmis = u_data.get("profil", {}), u_data.get("gecmis", {})
            isim = profil.get("isim", kadi)
            
            if arama_metni and (arama_metni not in kadi.lower() and arama_metni not in isim.lower()): continue
                
            sifre_text = hesap.to_dict().get("sifre", "Bilinmiyor")
            kayit_tarihi = hesap.to_dict().get("kayit_tarihi", "Bilinmiyor")
            
            kilo = float(profil.get("kilo", profil.get("baslangic_kilo", 0)))
            baslangic = float(profil.get("baslangic_kilo", 0))
            hedef = float(profil.get("hedef_kilo", 0))
            boy = int(profil.get("boy", 175))
            cinsiyet = profil.get("cinsiyet", "Bilinmiyor")
            verilen = baslangic - kilo
            vki = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            
            with st.expander(f"👤 {isim} (@{kadi})   |   ⚖️ Güncel: {kilo} kg   |   📅 Aktif: {len(gecmis.keys())} Gün"):
                if profil.get("foto_base64"):
                    pc, _ = st.columns([1, 8])
                    pc.markdown(f'<img src="data:image/png;base64,{profil["foto_base64"]}" class="custom-pp" style="width:100%; border-radius:10px;">', unsafe_allow_html=True)
                
                td, ta = st.tabs(["📊 Gelişmiş İstatistikler", "⚙️ Hesap Ayarları & İşlemler"])
                with td:
                    d_c1, d_c2, d_c3, d_c4 = st.columns(4)
                    d_c1.metric("Kayıt Tarihi", kayit_tarihi); d_c2.metric("Cinsiyet / Boy", f"{cinsiyet[:1]} - {boy} cm")
                    d_c3.metric("Başlangıç", f"{baslangic} kg"); d_c4.metric("VKİ", f"{vki:.1f}")
                    st.write("")
                    d_c5, d_c6, d_c7, d_c8 = st.columns(4)
                    d_c5.metric("Hedef Kilo", f"{hedef} kg")
                    d_c6.metric("Verilen", f"{verilen:.1f} kg", delta=f"{-verilen:.1f} kg" if verilen > 0 else "0", delta_color="inverse")
                    if (baslangic - hedef) > 0:
                        st.progress(gorsel_ilerleme(verilen/(baslangic-hedef)), text=f"Hedefe Ulaşma Oranı: %{(verilen/(baslangic-hedef)) * 100:.7f}")

                with ta:
                    a_c1, a_c2 = st.columns(2)
                    with a_c1:
                        yeni_sifre = st.text_input("Kullanıcının Yeni Şifresi", value=sifre_text, key=f"sif_{kadi}")
                        if st.button("Şifreyi Güncelle", key=f"btn_sif_{kadi}", use_container_width=True):
                            db_firestore.collection("hesaplar").document(kadi).update({"sifre": yeni_sifre}); st.success("Güncellendi!"); st.rerun()
                    with a_c2:
                        yeni_kadi = st.text_input("Yeni Kullanıcı Adı", value=kadi, key=f"kad_{kadi}")
                        if st.button("Kullanıcı Adını Değiştir", key=f"btn_kad_{kadi}", use_container_width=True):
                            if db_firestore.collection("hesaplar").document(yeni_kadi).get().exists: st.error("Bu isim alınmış!")
                            else:
                                e_hesap = hesap.to_dict()
                                e_hesap["sifre"] = yeni_sifre
                                db_firestore.collection("hesaplar").document(yeni_kadi).set(e_hesap)
                                db_firestore.collection("kullanici_verileri").document(yeni_kadi).set(u_data)
                                db_firestore.collection("hesaplar").document(kadi).delete()
                                db_firestore.collection("kullanici_verileri").document(kadi).delete()
                                st.success("Değiştirildi!"); st.rerun()
                    st.divider()
                    if st.button("🔍 Kullanıcının Panelini İncele", key=f"view_{kadi}", type="primary", use_container_width=True):
                        st.session_state.incelenen_kullanici = kadi; st.session_state.panel_kapat = True; st.rerun()

    # ---------------------------------------------------------
    # 3.2. KULLANICI (VEYA İNCELEME YAPAN ADMIN) GÖRÜNÜMÜ
    # ---------------------------------------------------------
    else:
        if kullanici_adi == "admin":
            kullanici_adi = st.session_state.incelenen_kullanici
            is_admin_viewing = True

        doc_ref = db_firestore.collection("kullanici_verileri").document(kullanici_adi)
        db = doc_ref.get().to_dict() if doc_ref.get().exists else {"profil": {"isim": kullanici_adi}, "gecmis": {}}

        def verileri_kaydet(data):
            if not is_admin_viewing: doc_ref.set(data)

        def gunluk_toplam_guncelle(tarih):
            if not is_admin_viewing:
                db["gecmis"][tarih]["toplam"] = sum(o.get("toplam_kalori", 0) for o in db["gecmis"][tarih].get("ogünler", []))
                db["gecmis"][tarih]["toplam_p"] = sum(o.get("toplam_p", 0) for o in db["gecmis"][tarih].get("ogünler", []))
                db["gecmis"][tarih]["toplam_c"] = sum(o.get("toplam_c", 0) for o in db["gecmis"][tarih].get("ogünler", []))
                db["gecmis"][tarih]["toplam_y"] = sum(o.get("toplam_y", 0) for o in db["gecmis"][tarih].get("ogünler", []))
                verileri_kaydet(db)

        # Değişkenler
        p = db["profil"]
        isim, kilo = p.get("isim", kullanici_adi), float(p.get("kilo", p.get("baslangic_kilo", 80.0)))
        boy, cinsiyet = int(p.get("boy", 175)), p.get("cinsiyet", "Erkek")
        baslangic, hedef_kilo = float(p.get("baslangic_kilo", 80.0)), float(p.get("hedef_kilo", 70.0))
        hedef_gun = int(p.get("hedef_gun", 30))

        try: dt_val = datetime.datetime.strptime(p.get("dogum_tarihi", "2000-01-01"), "%Y-%m-%d").date()
        except: dt_val = datetime.date(2000, 1, 1)
        yas = datetime.date.today().year - dt_val.year - ((datetime.date.today().month, datetime.date.today().day) < (dt_val.month, dt_val.day))

        verilen_kilo = baslangic - kilo
        tdee = ((10 * kilo) + (6.25 * boy) - (5 * yas) + (5 if cinsiyet == "Erkek" else -161)) * 1.3 
        orijinal_gunluk_limit = int(tdee - (((baslangic - hedef_kilo) * 7700) / hedef_gun)) if hedef_gun > 0 else int(tdee)
        hedef_su_litre, hedef_protein = round(kilo * 0.035, 1), int(kilo * 1.8)
        hedef_yag = int((orijinal_gunluk_limit * 0.25) / 9) 
        hedef_karb = int((orijinal_gunluk_limit - (hedef_protein * 4) - (hedef_yag * 9)) / 4)

        # --- YAN MENÜ (SIDEBAR) ---
        with st.sidebar:
            if is_admin_viewing:
                if st.button("⬅️ Admin Paneline Dön", type="primary", use_container_width=True):
                    st.session_state.incelenen_kullanici = None; st.session_state.panel_kapat = True; st.rerun()
            if p.get("foto_base64"):
                st.markdown(f'<div style="text-align:center;"><img src="data:image/png;base64,{p["foto_base64"]}" class="custom-pp" style="width:120px; height:120px; border-radius:50%; object-fit:cover; border:3px solid #2ecc71;"></div>', unsafe_allow_html=True)
            st.markdown(f"<h3 style='text-align:center; margin-top:10px;'>{isim}</h3>", unsafe_allow_html=True)
            
            if not is_admin_viewing:
                c_sb1, c_sb2 = st.columns(2)
                if c_sb1.button("⚙️ Ayarlar", use_container_width=True): st.session_state.aktif_sayfa = "Hesap Ayarları"; st.session_state.panel_kapat = True; st.rerun()
                if c_sb2.button("🚪 Çıkış", use_container_width=True, type="primary"): st.session_state.aktif_kullanici = None; st.rerun()

            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
            
            def profil_kaydet(k, v_key):
                if not is_admin_viewing:
                    db["profil"][k] = str(st.session_state[v_key]) if isinstance(st.session_state[v_key], datetime.date) else st.session_state[v_key]
                    if k in ["kilo", "baslangic_kilo"]: db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today())
                    verileri_kaydet(db)
                
            def profil_sil(k):
                if not is_admin_viewing and k in db["profil"]: del db["profil"][k]; verileri_kaydet(db)

            with st.expander("👤 Kişisel Bilgiler", expanded=False):
                c1, c2 = st.columns([5,2])
                c1.text_input("İsim", p.get("isim", kullanici_adi), key="w_isim", on_change=profil_kaydet, args=("isim", "w_isim"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_isim", on_click=profil_sil, args=("isim",), disabled=is_admin_viewing)
                
                c1, c2 = st.columns([5,2])
                c1.selectbox("Cinsiyet", ["Erkek", "Kadın"], index=0 if p.get("cinsiyet", "Erkek") == "Erkek" else 1, key="w_cins", on_change=profil_kaydet, args=("cinsiyet", "w_cins"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_cins", on_click=profil_sil, args=("cinsiyet",), disabled=is_admin_viewing)
                
                c1, c2 = st.columns([5,2])
                c1.date_input("Doğum Tarihi", dt_val, min_value=datetime.date(1940,1,1), key="w_dt", on_change=profil_kaydet, args=("dogum_tarihi", "w_dt"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_dt", on_click=profil_sil, args=("dogum_tarihi",), disabled=is_admin_viewing)
                
                c1, c2 = st.columns([5,2])
                c1.number_input("Boy (cm)", 100, 250, boy, key="w_boy", on_change=profil_kaydet, args=("boy", "w_boy"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_boy", on_click=profil_sil, args=("boy",), disabled=is_admin_viewing)

                c1, c2 = st.columns([5,2])
                c1.number_input("Başlangıç Kilosu (kg)", 30.0, 250.0, baslangic, step=0.5, key="w_bk", on_change=profil_kaydet, args=("baslangic_kilo", "w_bk"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_bk", on_click=profil_sil, args=("baslangic_kilo",), disabled=is_admin_viewing)

            # 10 Günlük Kilo Takibi Mantığı
            son_tarih_str = p.get("son_kilo_guncelleme", p.get("kayit_tarihi", str(datetime.date.today())))
            try:
                kilo_acik = (datetime.date.today() - datetime.datetime.strptime(son_tarih_str, "%Y-%m-%d").date()).days >= 10
            except: kilo_acik = False

            with st.expander("⚖️ Güncel Kilo Takibi", expanded=kilo_acik):
                if kilo_acik: st.warning("Kilonuzu güncelleme vaktiniz geldi!")
                st.number_input("Güncel Kilo (kg)", 30.0, 250.0, kilo, step=0.5, key="w_gk", on_change=profil_kaydet, args=("kilo", "w_gk"), disabled=is_admin_viewing)
                if not is_admin_viewing:
                    cb1, cb2 = st.columns(2)
                    if cb1.button("🔄 Sıfırla", use_container_width=True): profil_sil("kilo"); profil_sil("son_kilo_guncelleme"); st.rerun()
                    if cb2.button("💾 Kaydet", use_container_width=True, type="primary"): db["profil"]["son_kilo_guncelleme"] = str(datetime.date.today()); verileri_kaydet(db); st.success("Kaydedildi!"); st.rerun()

            with st.expander("🎯 Hedeflerim", expanded=False):
                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Kilo (kg)", 30.0, 200.0, hedef_kilo, step=0.5, key="w_hk", on_change=profil_kaydet, args=("hedef_kilo", "w_hk"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_hk", on_click=profil_sil, args=("hedef_kilo",), disabled=is_admin_viewing)

                c1, c2 = st.columns([5,2])
                c1.number_input("Hedef Süre (Gün)", 1, 730, hedef_gun, key="w_hg", on_change=profil_kaydet, args=("hedef_gun", "w_hg"), disabled=is_admin_viewing)
                with c2: st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True); st.button("🗑️", key="del_hg", on_click=profil_sil, args=("hedef_gun",), disabled=is_admin_viewing)

            st.divider()
            toplam_acik_panel = sum(max(0, int(tdee) - (v.get("toplam", 0) - v.get("yakilan_kalori", 0))) for v in db["gecmis"].values() if v.get("toplam", 0) > 0)
            ilerleme_orani = max(0.0, min(toplam_acik_panel / ((baslangic-hedef_kilo)*7700), 1.0)) if (baslangic-hedef_kilo) > 0 else 0.0
            
            st.markdown("### 🏆 Başarı Merkezi")
            m_c1, m_c2 = st.columns(2)
            m_c1.metric("Verilen", f"{verilen_kilo:.1f} kg")
            m_c2.metric("Kalan", f"{toplam_verilecek:.1f} kg")
            st.progress(gorsel_ilerleme(ilerleme_orani), text=f"Hedefe Ulaşma: %{ilerleme_orani * 100:.7f}")

        # --- SAYFA İÇERİĞİ YÖNLENDİRMELERİ ---
        if is_admin_viewing: st.warning(f"👁️ İZLEME MODU: Kullanıcı **{kullanici_adi}** paneli görüntüleniyor.")

        if st.session_state.aktif_sayfa == "Hesap Ayarları":
            if st.button("⬅️ Ana Menüye Dön"): st.session_state.aktif_sayfa = "📅 Günlük Takip"; st.rerun()
            st.title("⚙️ Hesap Yönetimi")
            
            if is_admin_viewing: st.error("Admin olarak bu işlemi yapamazsınız.")
            else:
                tab_h1, tab_h2, tab_h3 = st.tabs(["📸 Fotoğraf", "🔐 Şifre", "🏷️ Kullanıcı Adı"])
                with tab_h1:
                    up_pp = st.file_uploader("Fotoğraf Seç (JPG/PNG)", type=["png", "jpg", "jpeg"])
                    if up_pp and st.button("💾 Kaydet", use_container_width=True, type="primary"):
                        img = Image.open(up_pp); img.thumbnail((250, 250))
                        buf = io.BytesIO(); img.save(buf, format="PNG")
                        db["profil"]["foto_base64"] = base64.b64encode(buf.getvalue()).decode()
                        verileri_kaydet(db); st.success("Güncellendi!"); st.rerun()
                    if p.get("foto_base64") and st.button("🗑️ Kaldır", use_container_width=True):
                        del db["profil"]["foto_base64"]; verileri_kaydet(db); st.rerun()

                with tab_h2:
                    s1 = st.text_input("Mevcut Şifre", type="password")
                    s2 = st.text_input("Yeni Şifre", type="password")
                    s3 = st.text_input("Yeni Şifre (Tekrar)", type="password")
                    if st.button("🔐 Şifreyi Güncelle", use_container_width=True):
                        g_sif = db_firestore.collection("hesaplar").document(kullanici_adi).get().to_dict().get("sifre", "")
                        if s1 != g_sif: st.error("Şifre yanlış!")
                        elif not s2 or s2 != s3: st.error("Yeni şifreler eşleşmiyor!")
                        else:
                            db_firestore.collection("hesaplar").document(kullanici_adi).update({"sifre": s2})
                            st.session_state.aktif_kullanici = None; st.success("Değiştirildi! Tekrar giriş yapın."); st.rerun()

                with tab_h3:
                    k1 = st.text_input("Mevcut Kullanıcı Adı").strip().lower()
                    k2 = st.text_input("Yeni Kullanıcı Adı").strip().lower()
                    k3 = st.text_input("Yeni Ad (Tekrar)").strip().lower()
                    if st.button("🏷️ Kullanıcı Adını Güncelle", use_container_width=True):
                        if k1 != kullanici_adi: st.error("Ad yanlış!")
                        elif " " in k2 or not k2: st.error("Boşluk olamaz!")
                        elif k2 != k3: st.error("Eşleşmiyor!")
                        elif db_firestore.collection("hesaplar").document(k2).get().exists: st.error("Alınmış!")
                        else:
                            e_veri = db_firestore.collection("hesaplar").document(kullanici_adi).get().to_dict()
                            db_firestore.collection("hesaplar").document(k2).set(e_veri)
                            db_firestore.collection("kullanici_verileri").document(k2).set(db)
                            db_firestore.collection("hesaplar").document(kullanici_adi).delete()
                            db_firestore.collection("kullanici_verileri").document(kullanici_adi).delete()
                            st.session_state.aktif_kullanici = None; st.success("Değiştirildi! Tekrar giriş yapın."); st.rerun()

        # ANA İŞLEM SAYFALARI (TAKİP VE KOÇLUK)
        else:
            st.radio("Menü:", ["📅 Günlük Takip", "🤖 Koçluk Merkezi"], key="aktif_sayfa", horizontal=True, label_visibility="collapsed")
            
            if st.session_state.aktif_sayfa == "📅 Günlük Takip":
                if 'secili_tarih' not in st.session_state: st.session_state.secili_tarih = datetime.date.today()

                # TARİH KUTUSU
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
                    verileri_kaydet(db)

                # Dünkü Kaçamak Bildirimi
                dun_str = str(st.session_state.secili_tarih - datetime.timedelta(days=1))
                gunluk_limit = orijinal_gunluk_limit 
                
                if dun_str in db["gecmis"]:
                    dun_v = db["gecmis"][dun_str]
                    dun_su, dun_hedef_su = dun_v.get("su_litre", 0), dun_v.get("su_hedef", 2.5)
                    if dun_su < dun_hedef_su: st.warning(f"💧 Dün suyu tamamlayamadın ({dun_su}L / {dun_hedef_su}L).")
                    
                    dun_net = max(0, dun_v.get("toplam", 0) - dun_v.get("yakilan_kalori", 0))
                    if dun_v.get("toplam", 0) > 0: 
                        fark = dun_net - orijinal_gunluk_limit
                        if fark > 0:
                            telafi = fark // 3
                            gunluk_limit = orijinal_gunluk_limit - telafi 
                            st.warning(f"⚖️ Dün hedefini **{fark} kcal** aştın. Bugünkü hedeften **{telafi} kcal** kısıldı.")

                # ALT SEKMELER
                tab_ekle, tab_ozet, tab_egzersiz = st.tabs(["🍽️ Yiyecek Ekle & Menü", "📊 Günlük Özet & Su", "🏃 Egzersiz"])

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
                                st.info(st.session_state.onay_bekleyen_metin)
                                c_evet, c_hayir = st.columns(2)
                                
                                if c_evet.button("✅ Evet (Tabağa Ekle)", use_container_width=True, type="primary"):
                                    ogun_tipi = st.session_state.kaydedilecek_ogun_tipi
                                    json_v = st.session_state.json_veri
                                    
                                    # AKILLI BİRLEŞTİRME (Smart Merge)
                                    mevcut_idx = -1
                                    for i, ogun in enumerate(db["gecmis"][islem_tarihi]["ogünler"]):
                                        if ogun["tip"] == ogun_tipi: mevcut_idx = i; break
                                    
                                    t_kcal = sum(x.get('kalori',0) for x in json_v)
                                    t_p = sum(x.get('p',0) for x in json_v)
                                    t_c = sum(x.get('c',0) for x in json_v)
                                    t_y = sum(x.get('y',0) for x in json_v)

                                    if mevcut_idx != -1:
                                        db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["kalemler"].extend(json_v)
                                        db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_kalori"] += t_kcal
                                        db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_p"] += t_p
                                        db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_c"] += t_c
                                        db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_y"] += t_y
                                    else:
                                        db["gecmis"][islem_tarihi]["ogünler"].append({
                                            "tip": ogun_tipi, "kalemler": json_v, 
                                            "toplam_kalori": t_kcal, "toplam_p": t_p, "toplam_c": t_c, "toplam_y": t_y
                                        })
                                        
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
                                    
                                    cm, cb = st.columns(2)
                                    ymk_mik = cm.number_input("Miktar", 0.01, 1000.0, 1.0, 0.5)
                                    ymk_brm = cb.selectbox("Birim", ["porsiyon", "adet", "dilim", "kase", "bardak", "gram", "yemek kaşığı", "avuç"])
                                    
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
                                            with st.spinner("AI dikkatlice hesaplıyor..."):
                                                prompt = f"""Kullanıcı yediği menü: {", ".join(st.session_state.tabak_listesi)}. 
                                                Tüm yiyeceklerin kalori, Protein(p), Karb(c), Yağ(y) değerlerini TAM SAYI hesapla.
                                                SADECE VE SADECE JSON DİZİSİ OLARAK YANIT VER.
                                                Örnek Format: [{{"ad": "1 Porsiyon Pilav", "kalori": 250, "p": 5, "c": 40, "y": 5}}]"""
                                                
                                                res = model.generate_content(prompt)
                                                v_list = guvenli_json_oku(res.text)
                                                
                                                metin = ""
                                                for item in v_list: metin += f"- {item.get('ad','Bilinmeyen')}: **{item.get('kalori',0)} kcal** | {item.get('p',0)}P | {item.get('c',0)}K | {item.get('y',0)}Y\n"
                                                metin += f"\n**TOPLAM: {sum(x.get('kalori',0) for x in v_list)} kcal**"
                                                
                                                st.session_state.json_veri = v_list
                                                st.session_state.onay_bekleyen_metin = metin
                                                st.rerun()

                                with t_foto:
                                    st.info("📸 Fotoğrafı yükle, gerisini AI halletsin!")
                                    foto_ogun = st.selectbox("Öğün Seç", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün", "Atıştırmalık"])
                                    yuklenen = st.file_uploader("Fotoğraf Seç", type=["jpg", "jpeg", "png"])
                                    ipucu = st.text_input("💡 İpucu ver", placeholder="Örn: Fırın makarna")
                                    
                                    if yuklenen:
                                        img = Image.open(yuklenen)
                                        st.image(img, use_container_width=True)
                                        if st.button("🚀 Detaylı Analiz Et", type="primary", use_container_width=True):
                                            st.session_state.kaydedilecek_ogun_tipi = foto_ogun
                                            with st.spinner("AI fotoğrafı yavaş ve dikkatlice inceliyor..."):
                                                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                                                ek_b = f"Kullanıcı bu yemeğin '{ipucu}' olduğunu belirtti. " if ipucu else ""
                                                
                                                # KARTAL GÖZÜ PROMPTU
                                                prompt = f"""{ek_b}Lütfen fotoğrafı DİKKATLİCE analiz et. Tabakta veya masada ne kadar FARKLI ÇEŞİT yiyecek/içecek varsa hepsini TEK TEK tespit et (Örn: Sadece kahvaltıyı bütün olarak yazma; yumurtayı, peyniri, çayı ayrı ayrı bul).
                                                Her birinin porsiyon tahminini yap ve değerlerini hesapla.
                                                SADECE VE SADECE JSON DİZİSİ OLARAK YANIT VER.
                                                Örnek Format:
                                                [
                                                  {{"ad": "1 Adet Yumurta", "kalori": 78, "p": 6, "c": 1, "y": 5}},
                                                  {{"ad": "2 Dilim Peynir", "kalori": 120, "p": 8, "c": 2, "y": 10}}
                                                ]"""
                                                
                                                res = model.generate_content([prompt, img])
                                                v_list = guvenli_json_oku(res.text)
                                                
                                                metin = ""
                                                for item in v_list: metin += f"- {item.get('ad','Bilinmeyen')}: **{item.get('kalori',0)} kcal** | {item.get('p',0)}P | {item.get('c',0)}K | {item.get('y',0)}Y\n"
                                                metin += f"\n**TOPLAM: {sum(x.get('kalori',0) for x in v_list)} kcal**"
                                                
                                                st.session_state.json_veri = v_list
                                                st.session_state.onay_bekleyen_metin = metin
                                                st.rerun()
                                    
                                with t_manuel:
                                    m_ogun = st.selectbox("Öğün", ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün"])
                                    m_ad = st.text_input("Yemek Adı")
                                    c1, c2, c3, c4 = st.columns(4)
                                    m_k = c1.number_input("Kcal", 0, 5000, 100)
                                    m_p = c2.number_input("P(g)", 0, 500, 0)
                                    m_c = c3.number_input("Karb", 0, 500, 0)
                                    m_y = c4.number_input("Yağ", 0, 500, 0)
                                    
                                    if st.button("Listeye Ekle", use_container_width=True) and m_ad:
                                        # Manuel Akıllı Birleştirme
                                        mevcut_idx = -1
                                        for i, ogun in enumerate(db["gecmis"][islem_tarihi]["ogünler"]):
                                            if ogun["tip"] == m_ogun: mevcut_idx = i; break
                                            
                                        y_kalem = {"ad": m_ad, "kalori": m_k, "p":m_p, "c":m_c, "y":m_y}
                                        
                                        if mevcut_idx != -1:
                                            db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["kalemler"].append(y_kalem)
                                            db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_kalori"] += m_k
                                            db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_p"] += m_p
                                            db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_c"] += m_c
                                            db["gecmis"][islem_tarihi]["ogünler"][mevcut_idx]["toplam_y"] += m_y
                                        else:
                                            db["gecmis"][islem_tarihi]["ogünler"].append({
                                                "tip": m_ogun, "kalemler": [y_kalem], 
                                                "toplam_kalori": m_k, "toplam_p": m_p, "toplam_c": m_c, "toplam_y": m_y
                                            })
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

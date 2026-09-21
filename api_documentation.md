# MovieApp API

Test dosyalarındaki (`HDFilmcehennemiTest.py`, `DiziboxTest.py`) interaktif CLI işlevlerini HTTP endpoint'leri olarak sunan FastAPI tabanlı REST API.

## Endpoint Haritası

| Yöntem | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/` | API sağlık kontrolü |
| `GET` | `/api/plugins` | Tüm eklentileri listele |
| `GET` | `/api/plugins/{name}` | Eklenti detayı |
| `GET` | `/api/plugins/{name}/categories` | Eklenti kategorileri |
| `GET` | `/api/plugins/{name}/main-page` | Ana sayfa / kategori içerikleri |
| `GET` | `/api/plugins/{name}/search?q=...` | Tek eklentide arama |
| `GET` | `/api/plugins/{name}/detail?url=...` | İçerik detayı (film / dizi) |
| `GET` | `/api/plugins/{name}/links?url=...` | İzleme bağlantıları |
| `GET` | `/api/search?q=...` | **Tüm eklentilerde** arama |
| `GET` | `/api/extractors` | Yüklü extractor'ları listele |
| `POST` | `/api/extract` | URL'den medya çıkar |

## Örnek Kullanım

### Tüm eklentileri listele
```
GET http://localhost:8000/api/plugins
```

### HDFilmCehennemi'de arama yap
```
GET http://localhost:8000/api/plugins/HDFilmCehennemi/search?q=inception
```

### Tüm eklentilerde aynı anda arama yap
```
GET http://localhost:8000/api/search?q=breaking+bad
```

### Film detayını getir
```
GET http://localhost:8000/api/plugins/HDFilmCehennemi/detail?url=https://www.hdfilmcehennemi.nl/baslangic-hd-film-izle-9/
```

### İzleme bağlantılarını getir
```
GET http://localhost:8000/api/plugins/HDFilmCehennemi/links?url=https://www.hdfilmcehennemi.nl/baslangic-hd-film-izle-9/
```

### URL'den medya çıkar (Extract)
```
POST http://localhost:8000/api/extract
Content-Type: application/json

{
  "url": "https://vidmoly.biz/embed-xxxxx.html",
  "referer": "https://www.hdfilmcehennemi.nl/"
}
```

## Dosya Yapısı

```
api/
├── __init__.py        # Paket tanımı
├── app.py             # FastAPI uygulama nesnesi ve yaşam döngüsü
├── deps.py            # Singleton PluginManager & ExtractorManager
└── routes/
    ├── __init__.py    # Router export'ları
    ├── plugins.py     # Plugin endpoint'leri (/api/plugins/...)
    └── extractors.py  # Extractor endpoint'leri (/api/extractors, /api/extract)
```

## CLI ↔ API Eşleştirmesi

| CLI İşlevi | API Karşılığı |
|-------------|---------------|
| `eklenti_ile_arama()` | `GET /api/plugins/{name}/search?q=...` |
| `get_main_page()` | `GET /api/plugins/{name}/main-page` |
| `sonuc_detaylari_goster()` | `GET /api/plugins/{name}/detail?url=...` |
| `baglanti_secenekleri_goster()` | `GET /api/plugins/{name}/links?url=...` |
| `extractor_ile_oynat()` | `POST /api/extract` |
| Tüm eklentilerde arama | `GET /api/search?q=...` |

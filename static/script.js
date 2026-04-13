document.addEventListener('DOMContentLoaded', function() {
    if ($.fn.DataTable) {
        $('.data-table').DataTable({
            language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/tr.json' },
            pageLength: 10,
            responsive: true,
            order: [[0, 'desc']]
        });
    }
});

function silmeOnayi(event, formElement) {
    event.preventDefault(); 
    Swal.fire({
        title: 'Emin misiniz?',
        text: "Bu veriyi sildiğinizde geri alamazsınız!",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="bi bi-trash"></i> Evet, Sil!',
        cancelButtonText: 'İptal'
    }).then((result) => {
        if (result.isConfirmed) { formElement.submit(); }
    });
}

function gecmisGoster(id, isim) {
    fetch(`/fiyat_gecmisi/${id}`)
        .then(response => response.json())
        .then(data => {
            let listeHtml = '<ul class="list-group">';
            if (data.gecmis.length === 0) {
                listeHtml += '<li class="list-group-item text-muted">Henüz fiyat değişimi kaydedilmemiş.</li>';
            } else {
                data.gecmis.forEach(item => {
                    let utcTarih = item.degisim_tarihi.replace(' ', 'T') + 'Z';
                    let tarih = new Date(utcTarih).toLocaleString('tr-TR', {
                        year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'
                    });
                    listeHtml += `
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <span class="fw-bold">${item.eski_fiyat} ₺</span>
                            <span class="badge bg-secondary rounded-pill">${tarih}</span>
                        </li>`;
                });
            }
            listeHtml += '</ul>';
            
            Swal.fire({
                title: `<i class="bi bi-clock-history text-info"></i> ${isim}`,
                html: listeHtml,
                confirmButtonText: 'Kapat',
                confirmButtonColor: '#6c757d'
            });
        });
}

function fisTaraBtn() {
    const form = document.getElementById('fisForm');
    const formData = new FormData(form);
    
    Swal.fire({
        title: 'Fiş Okunuyor...',
        html: 'Yapay zeka görseli çözümlüyor, lütfen bekleyin...',
        icon: 'info',
        allowOutsideClick: false,
        didOpen: () => { Swal.showLoading() }
    });

    fetch('/fis_tara', { method: 'POST', body: formData })
    .then(response => response.json())
    .then(data => {
        if(data.hata) {
            Swal.fire('Hata!', data.hata, 'error');
        } else {
            let html = '<p class="text-muted small">İşlemek istemediğiniz ürünleri yandaki kırmızı çarpı butonuna basarak listeden çıkarabilirsiniz.</p>';
            html += '<ul class="list-group text-start mt-3" id="fis-onay-listesi">';
            
            data.sonuclar.forEach(d => {
                if (d.durum === 'degismedi') {
                    html += `
                    <li class="list-group-item d-flex justify-content-between align-items-center bg-light">
                        <div><i class="bi bi-check-circle-fill text-success me-2"></i> <span class="text-muted">${d.ad} (Fiyat Aynı: ${d.yeni_fiyat} ₺)</span></div>
                    </li>`;
                    return; 
                }

                let badge = d.durum === 'guncellenecek' ? '<span class="badge bg-warning text-dark me-2">GÜNCELLE</span>' : '<span class="badge bg-success me-2">YENİ ÜRÜN</span>';
                let detay = d.durum === 'guncellenecek' ? `${d.eski_fiyat} ₺ <i class="bi bi-arrow-right"></i> <strong class="text-danger">${d.yeni_fiyat} ₺</strong>` : `<strong class="text-success">${d.yeni_fiyat} ₺</strong>`;
                
                html += `
                <li class="list-group-item d-flex justify-content-between align-items-center fis-item" data-ad="${d.ad}" data-fiyat="${d.yeni_fiyat}" data-durum="${d.durum}">
                    <div>
                        ${badge} <b>${d.ad}</b> <br> <small class="text-muted">${detay}</small>
                    </div>
                    <button class="btn btn-sm text-danger p-0 ms-2 border-0 bg-transparent" title="Bu ürünü iptal et" onclick="this.closest('li').remove()">
                        <i class="bi bi-x-circle-fill fs-3"></i>
                    </button>
                </li>`;
            });
            html += '</ul>';

            Swal.fire({
                title: 'Önizleme ve Onay',
                html: html,
                width: '600px',
                showCloseButton: true,
                showCancelButton: true,
                confirmButtonColor: '#198754',
                cancelButtonColor: '#6c757d',
                confirmButtonText: '<i class="bi bi-save"></i> Seçilenleri Onayla',
                cancelButtonText: 'İşlemi İptal Et',
                preConfirm: () => {
                    let onaylananVeriler = [];
                    document.querySelectorAll('.fis-item').forEach(item => {
                        onaylananVeriler.push({
                            ad: item.getAttribute('data-ad'),
                            yeni_fiyat: item.getAttribute('data-fiyat'),
                            durum: item.getAttribute('data-durum')
                        });
                    });
                    if (onaylananVeriler.length === 0) {
                        Swal.showValidationMessage('Kaydedilecek hiçbir ürün kalmadı!');
                        return false;
                    }
                    return onaylananVeriler;
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    fetch('/fis_kaydet', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(result.value)
                    })
                    .then(res => res.json())
                    .then(kayitData => {
                        Swal.fire('Başarılı!', kayitData.mesaj, 'success').then(() => location.reload());
                    });
                }
            });
        }
    })
    .catch(err => Swal.fire('Bağlantı Hatası', 'Sunucu ile iletişim kurulamadı.', 'error'));
}

function uyariKapat(tip, id) {
    let url = tip === 'tarif' ? `/uyari_kapat_tarif/${id}` : `/uyari_kapat_malzeme/${id}`;
    let elementId = `uyari-${tip}-${id}`;
    
    fetch(url, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        if (data.durum === 'basarili') {
            let badge = document.getElementById(elementId);
            if (badge) {
                badge.style.transition = "all 0.3s ease-in-out";
                badge.style.transform = "scale(0.5)";
                badge.style.opacity = "0";
                setTimeout(() => badge.remove(), 300); 
            }
        }
    })
    .catch(err => console.error("Uyarı kapatılamadı:", err));
}

function masaBosaltOnayi(event, formElement) {
    event.preventDefault(); 
    Swal.fire({
        title: 'Masayı Boşalt?',
        text: "Müşteri masadan kalktıysa (hesap ödendiyse), masayı sistemden kaldırıp tekrar yeşil duruma getirebilirsiniz.",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#198754',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="bi bi-check-circle"></i> Evet, Masayı Boşalt',
        cancelButtonText: 'İptal'
    }).then((result) => {
        if (result.isConfirmed) {
            formElement.submit(); 
        }
    });
}

// YENİ: Z RAPORU GÜN SONU FONKSİYONU
function gunSonuRaporu() {
    Swal.fire({
        title: 'Günü Kapatmak İstediğinize Emin Misiniz?',
        text: "Bu işlem, bugün 'Hesabı Kapatılan' tüm siparişleri hesaplayıp bir Z Raporu oluşturacak. Onaylandıktan sonra bu siparişler dondurulacaktır.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#212529',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="bi bi-calculator"></i> Evet, Z Raporu Al',
        cancelButtonText: 'İptal'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({title: 'Kâr ve Zarar Hesaplanıyor...', allowOutsideClick: false, didOpen: () => Swal.showLoading()});
            
            fetch('/gun_sonu', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                let icon = data.kar >= 0 ? 'success' : 'warning';
                let karRenk = data.kar >= 0 ? 'text-success' : 'text-danger';
                
                let mesaj = `
                    <div class="text-start mt-3">
                        <ul class="list-group">
                            <li class="list-group-item d-flex justify-content-between align-items-center">
                                <span><i class="bi bi-bag-check text-muted me-2"></i> Kapatılan Adisyon:</span> 
                                <strong class="fs-5">${data.siparis_sayisi} Adet</strong>
                            </li>
                            <li class="list-group-item d-flex justify-content-between align-items-center">
                                <span><i class="bi bi-cash-coin text-primary me-2"></i> Toplam Ciro (Satış):</span> 
                                <strong class="text-primary fs-5">${data.ciro.toFixed(2)} ₺</strong>
                            </li>
                            <li class="list-group-item d-flex justify-content-between align-items-center">
                                <span><i class="bi bi-basket2 text-danger me-2"></i> Toplam Hammadde Maliyeti:</span> 
                                <strong class="text-danger fs-5">${data.maliyet.toFixed(2)} ₺</strong>
                            </li>
                            <li class="list-group-item d-flex justify-content-between align-items-center bg-light border-top-0 mt-2">
                                <span class="fw-bold"><i class="bi bi-piggy-bank text-success me-2"></i> NET KÂR:</span> 
                                <strong class="${karRenk} fs-4">${data.kar.toFixed(2)} ₺</strong>
                            </li>
                        </ul>
                        <div class="text-muted small text-center mt-3">*Bu veriler sadece tamamlanmış siparişleri kapsar. Mutfaktaki siparişler dahil edilmez.</div>
                    </div>
                `;
                
                Swal.fire({
                    title: 'Gün Sonu (Z) Raporu',
                    html: mesaj,
                    icon: icon,
                    confirmButtonText: 'Tamam, Kapat'
                }).then(() => location.reload());
            })
            .catch(err => Swal.fire('Bağlantı Hatası', 'Z raporu hesaplanamadı.', 'error'));
        }
    });
}
// Turkish
export const tr = {
  hello: 'Merhaba',
  paywall: {
    title: "Manevi Yolculuğunuzu\nTamamlayın",
    cta: "Hemen Başlayın",
    ctaLoading: "İşleniyor...",
    renewalNotice: "Yenilenen ödeme, istediğiniz zaman iptal edebilirsiniz.",
    terms: "Kullanım Koşulları",
    privacy: "Gizlilik",
    restore: "Geri Yükle",
    savingsBadge: (percent: number) => `%${percent} İndirim`,
    perMonth: (price: string) => `${price}/ay`,
    perWeek: (price: string) => `${price} / hafta`,
    features: {
      audio_quran: "Sesli Kuran",
      feed_content: "50,000+ Ayet, Hadis, Esma",
      chat_ai: "Yapay Zeka Rehber",
      chat_room: "Mecliste Sohbet",
      widgets: "100+ iOS Widget",
      watermark: "Filigransız Paylaşım",
      offline_mode: "Çevrimdışı Modu",
      cloud_backup: "Bulut Yedekleme",
    },
    plans: {
      yearly: {
        title: "Yıllık",
        period: "/yıl",
      },
      monthly: {
        title: "Aylık",
        period: "/ay",
      },
    },
    lastChance: {
      only: "Sadece",
      warning: "Fırsat Sona Eriyor",
    },
    success: {
      title: "Tebrikler!",
      subtitle: "Premium üyeliğiniz aktifleşti.",
      description: "Tüm premium özelliklere sınırsız erişim kazandınız.",
      expiry: (date: string) => `Hesabınız ${date} tarihine kadar premium.`,
      cta: "Premium'u Kullanmaya Başla",
    },
  },
  tabs: {
    reflection: {
      title: "Yolculuk",
      subtitle: "Yolculuğunuzun günlük yansıması",
      habitsTracking: "Alışkanlıklar & Takip",
      journalNotes: "Günlük & Notlar",
      reminders: "Hatırlatıcılar",
    },
  },
};

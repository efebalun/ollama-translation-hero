// English
export const en = {
  hello: "Hello",
  paywall: {
    title: "Complete Your\nSpiritual Journey",
    cta: "Get Started Now",
    ctaLoading: "Processing...",
    renewalNotice: "Subscription renews automatically. Cancel anytime.",
    terms: "Terms of Use",
    privacy: "Privacy",
    restore: "Restore",
    savingsBadge: (percent: number) => `${percent}% Off`,
    perMonth: (price: string) => `${price}/mo`,
    perWeek: (price: string) => `${price} / week`,
    features: {
      audio_quran: "Audio Quran",
      feed_content: "50,000+ Verses, Hadiths, Names",
      chat_ai: "AI Spiritual Guide",
      chat_room: "Community Chat",
      widgets: "100+ iOS Widgets",
      watermark: "Watermark-Free Sharing",
      offline_mode: "Offline Mode",
      cloud_backup: "Cloud Backup",
    },
    plans: {
      yearly: {
        title: "Yearly",
        period: "/year",
      },
      monthly: {
        title: "Monthly",
        period: "/mo",
      },
    },
    lastChance: {
      only: "Only",
      warning: "Offer Expiring",
    },
    success: {
      title: "Congratulations!",
      subtitle: "Your premium membership is active.",
      description: "You now have unlimited access to all premium features.",
      expiry: (date: string) => `Your account is premium until ${date}.`,
      cta: "Start Using Premium",
    },
  },
  tabs: {
    reflection: {
      title: "Journey",
      subtitle: "Daily reflection of your journey",
      habitsTracking: "Habits & Tracking",
      journalNotes: "Journal & Notes",
      reminders: "Reminders",
    },
  },
};

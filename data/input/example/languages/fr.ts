// French
export const fr = {
  hello: "Bien",
  paywall: {
    title: "Complétez votre voyage spirituel\nComplétez",
    cta: "Commencer maintenant",
    ctaLoading: "Traitement en cours...",
    renewalNotice: "Vous pouvez annuler votre abonnement renouvelé à tout moment.",
    terms: "Conditions d'utilisation",
    privacy: "Confidentialité",
    restore: "Recharger",
    savingsBadge: (percent: number) => `%${percent} de réduction`,
    perMonth: (price: string) => `${price}/mois`,
    perWeek: (price: string) => `${price} / semaine`,
    features: {
      audio_quran: "Coran audio",
      feed_content: "50,000+ versets, hadiths, esma",
      chat_ai: "Guide IA",
      chat_room: "Discussion en Assemblée",
      widgets: "100+ widgets iOS",
      watermark: "Partage sans filigrane",
      offline_mode: "Mode hors ligne",
      cloud_backup: "Sauvegarde cloud",
    },
    plans: {
      yearly: {
        title: "Annuel",
        period: "/an",
      },
      monthly: {
        title: "Mensuel",
        period: "/mois",
      },
    },
    lastChance: {
      only: "Seulement",
      warning: "L'opportunité se termine",
    },
    success: {
      title: "Félicitations !",
      subtitle: "Votre abonnement premium est activé.",
      description: "Vous avez obtenu un accès illimité à toutes les fonctionnalités premium.",
      expiry: (date: string) => `Votre compte est premium jusqu'au ${date}.`,
      cta: "Commencer à utiliser Premium",
    },
  },
  tabs: {
    reflection: {
      title: "Voyage",
      subtitle: "Réflexion quotidienne de votre voyage",
      habitsTracking: "Habitudes & Suivi",
      journalNotes: "Journal & Notes",
      reminders: "Rappels",
    },
  },
};

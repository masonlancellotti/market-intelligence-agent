// SF-Symbol-like inline SVG icons (stroke-based, 20x20 viewport). Currentcolor.
const S = ({ children, ...p }: any) => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" {...p}>{children}</svg>
);

export const IconToday = (p: any) => <S {...p}><rect x="3" y="4" width="18" height="17" rx="3" /><path d="M3 9h18M8 2v4M16 2v4" /></S>;
export const IconMarkets = (p: any) => <S {...p}><path d="M3 17l5-6 4 4 5-7 4 5" /><path d="M3 21h18" /></S>;
export const IconSignals = (p: any) => <S {...p}><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 12l5-3" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /></S>;
export const IconMacro = (p: any) => <S {...p}><path d="M4 19V5M4 19h16" /><path d="M8 15l3-4 3 2 4-6" /></S>;
export const IconFilings = (p: any) => <S {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></S>;
export const IconBriefs = (p: any) => <S {...p}><path d="M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /><path d="M8 12h8M8 16h5M8 8h3" /></S>;
export const IconConviction = (p: any) => <S {...p}><path d="M12 3l2.5 5 5.5.8-4 3.9 1 5.5-5-2.6-5 2.6 1-5.5-4-3.9 5.5-.8z" /></S>;
export const IconJournal = (p: any) => <S {...p}><path d="M4 4h13a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z" /><path d="M8 8h8M8 12h8M8 16h4" /></S>;
export const IconSystem = (p: any) => <S {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></S>;
export const IconSearch = (p: any) => <S {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></S>;
export const IconBolt = (p: any) => <S {...p}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></S>;
export const IconSun = (p: any) => <S {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" /></S>;
export const IconMoon = (p: any) => <S {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></S>;
export const IconDot = (p: any) => <svg className="icon" viewBox="0 0 24 24" {...p}><circle cx="12" cy="12" r="5" fill="currentColor" /></svg>;

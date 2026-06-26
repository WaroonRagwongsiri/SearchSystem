import { Noto_Serif_Thai, Noto_Sans_Thai } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const serifThai = Noto_Serif_Thai({
  variable: "--font-serif-thai",
  subsets: ["latin", "thai"],
  display: "swap",
});

const sansThai = Noto_Sans_Thai({
  variable: "--font-sans-thai",
  subsets: ["latin", "thai"],
  display: "swap",
});

export const metadata = {
  title: "PocSearch — Historical Thai archive search",
  description:
    "Hybrid lexical · fuzzy · vector search over historical Thai documents.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${serifThai.variable} ${sansThai.variable}`}>
      <body>
        <nav className="nav">
          <div className="nav__inner">
            <Link href="/" className="brand" aria-label="PocSearch home">
              <span className="brand__mark" aria-hidden="true">
                ป
              </span>
              PocSearch
            </Link>
            <Link href="/add-word" className="nav__link">
              Add word map
            </Link>
            <Link href="/review" className="nav__link">
              Review
            </Link>
          </div>
        </nav>
        <main>{children}</main>
        <footer className="footer">
          <div className="footer__inner">
            <span>PocSearch · hybrid search over historical Thai documents</span>
            <span className="tnum">lexical · fuzzy · vector</span>
          </div>
        </footer>
      </body>
    </html>
  );
}

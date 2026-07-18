import { useState } from "react";
import { NavbarLogo } from "@/sections/Navbar/components/NavbarLogo";
import { DesktopMenu } from "@/sections/Navbar/components/DesktopMenu";
import { NavbarActions } from "@/sections/Navbar/components/NavbarActions";

export const Navbar = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] fixed no-underline w-screen z-[100] px-[19.2308px] py-[15.3846px] top-[46.1538px] inset-x-0 md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:px-[28.4444px] md:py-[21.3333px] md:top-[28.4444px]">
      <nav className="items-center box-border caret-transparent flex text-[15.3846px] justify-between tracking-[-0.107692px] leading-[21.5385px] max-w-[1153.85px] outline-[3px] relative no-underline w-full z-[1] mx-auto md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[1066.67px]">
        <div className="items-center box-border caret-transparent flex text-[15.3846px] justify-between tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] no-underline w-full md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
          <div className="items-center box-border caret-transparent gap-x-[19.2308px] flex basis-[0%] grow text-[15.3846px] justify-start tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[19.2308px] no-underline md:gap-x-[17.7778px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[17.7778px]">
            <NavbarLogo />
            <div className="bg-[color(srgb_1_1_1_/_0.12)] box-border caret-transparent hidden text-[15.3846px] h-[9.61538px] tracking-[-0.107692px] leading-[21.5385px] min-h-0 min-w-0 outline-[3px] no-underline w-px md:block md:text-[14.2222px] md:h-[8.88889px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto]"></div>
            <DesktopMenu />
          </div>
          <NavbarActions
            mobileOpen={mobileOpen}
            onToggle={() => setMobileOpen((open) => !open)}
          />
        </div>
      </nav>
      {mobileOpen && (
        <div className="strict-mobile-menu md:hidden">
          <a href="#methode" onClick={() => setMobileOpen(false)}>La méthode</a>
          <a href="#agents" onClick={() => setMobileOpen(false)}>Les agents</a>
          <a href="#module" onClick={() => setMobileOpen(false)}>Le module</a>
          <a href="#classe" onClick={() => setMobileOpen(false)}>La classe</a>
          <a href="#pilotage" onClick={() => setMobileOpen(false)}>Le pilotage</a>
          <a href="#faq" onClick={() => setMobileOpen(false)}>FAQ</a>
          <a href="/cours?p=3">Accès apprenant</a>
          <a className="strict-mobile-menu__primary" href="/connexion-centre?mode=signup">Créer un espace centre</a>
        </div>
      )}
    </div>
  );
};

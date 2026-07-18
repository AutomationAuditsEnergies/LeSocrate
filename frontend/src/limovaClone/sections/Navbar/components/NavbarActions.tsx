type NavbarActionsProps = {
  mobileOpen?: boolean;
  onToggle?: () => void;
};

export const NavbarActions = ({ mobileOpen = false, onToggle }: NavbarActionsProps) => {
  return (
    <div className="items-center box-border caret-transparent gap-x-[3.84615px] flex text-[15.3846px] justify-end tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] relative gap-y-[3.84615px] no-underline z-[4] md:gap-x-[normal] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:static md:gap-y-[normal] md:z-auto">
      <div className="items-center box-border caret-transparent gap-x-[7.69231px] hidden text-[15.3846px] justify-center tracking-[-0.107692px] leading-[21.5385px] min-h-0 min-w-0 outline-[3px] gap-y-[7.69231px] no-underline md:gap-x-[7.11111px] md:flex md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto] md:gap-y-[7.11111px]">
        <a
          href="/connexion-centre"
          className="items-center box-border caret-transparent flex text-[15.3846px] font-medium justify-center tracking-[-0.107692px] leading-[21.5385px] max-w-full min-h-0 min-w-0 outline-[3px] relative no-underline z-[1] px-[15.3846px] py-[7.69231px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto] md:px-[14.2222px] md:py-[7.11111px]"
        >
          <div className="items-center box-border caret-transparent gap-x-[7.69231px] flex text-[15.3846px] justify-center tracking-[-0.107692px] leading-[21.5385px] min-h-0 min-w-0 outline-[3px] relative gap-y-[7.69231px] no-underline z-[2] rounded-[375px] md:gap-x-[7.11111px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto] md:gap-y-[7.11111px] md:rounded-[1280px]">
            <div className="box-border caret-transparent flex text-[13.4615px] h-[18.8462px] tracking-[-0.107692px] leading-[18.8462px] min-h-0 min-w-0 outline-[3px] no-underline overflow-hidden md:text-[12.4444px] md:h-[17.4222px] md:tracking-[-0.0995556px] md:leading-[17.4222px] md:min-h-[auto] md:min-w-[auto]">
              <span className="box-border caret-transparent block text-[13.4615px] tracking-[-0.107692px] leading-[18.8462px] min-h-0 min-w-0 outline-[3px] no-underline md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px] md:min-h-[auto] md:min-w-[auto]">
                Se connecter
              </span>
            </div>
          </div>
          <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[color(srgb_1_1_1_/_0.06)] -outline-offset-1 outline outline-1 absolute no-underline z-0 rounded-[1523.08px] inset-0 md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:rounded-[1408px]"></div>
        </a>
        <a
          href="/cours?p=3"
          className="items-center box-border caret-transparent flex text-[15.3846px] font-medium justify-center tracking-[-0.107692px] leading-[21.5385px] max-w-full min-h-0 min-w-0 outline-[3px] relative no-underline z-[1] pl-[11.5385px] pr-[13.4615px] py-[5.76923px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto] md:pl-[10.6667px] md:pr-[12.4444px] md:py-[5.33333px]"
        >
          <div className="items-center box-border caret-transparent gap-x-[7.69231px] flex text-[15.3846px] justify-center tracking-[-0.107692px] leading-[21.5385px] min-h-0 min-w-0 outline-[3px] relative gap-y-[7.69231px] no-underline z-[2] rounded-[375px] md:gap-x-[7.11111px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:min-h-[auto] md:min-w-[auto] md:gap-y-[7.11111px] md:rounded-[1280px]">
            <div className="items-center box-border caret-transparent flex shrink-0 text-[15.3846px] h-[11.5385px] justify-center tracking-[-0.107692px] leading-[21.5385px] mb-[-0.769231px] [mask-image:linear-gradient(90deg,rgba(0,0,0,0)_0%,rgb(255,255,255)_10%,rgb(255,255,255)_90%,rgba(0,0,0,0)_100%)] min-h-0 min-w-0 outline-[3px] relative no-underline w-[11.5385px] md:text-[14.2222px] md:h-[10.6667px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:mb-[-0.711111px] md:min-h-[auto] md:min-w-[auto] md:w-[10.6667px]">
              <img
                src="https://c.animaapp.com/mrq6puj7YRWjJs/assets/icon-3.svg"
                alt="Icon"
                className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] no-underline w-full md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]"
              />
            </div>
            <div className="box-border caret-transparent flex text-[13.4615px] h-[18.8462px] tracking-[-0.107692px] leading-[18.8462px] min-h-0 min-w-0 outline-[3px] no-underline overflow-hidden md:text-[12.4444px] md:h-[17.4222px] md:tracking-[-0.0995556px] md:leading-[17.4222px] md:min-h-[auto] md:min-w-[auto]">
              <span className="box-border caret-transparent block text-[13.4615px] tracking-[-0.107692px] leading-[18.8462px] min-h-0 min-w-0 outline-[3px] no-underline md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px] md:min-h-[auto] md:min-w-[auto]">
                Accès apprenant
              </span>
            </div>
          </div>
          <div className="bg-[color(srgb_1_1_1_/_0.06)] shadow-[rgba(255,255,255,0.05)_0px_0px_32px_0px_inset,rgba(255,255,255,0.04)_0px_0px_6px_0px_inset] box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[color(srgb_1_1_1_/_0.06)] -outline-offset-1 outline outline-1 absolute no-underline z-0 rounded-[1523.08px] inset-0 md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:rounded-[1408px]"></div>
        </a>
      </div>
      <button
        aria-label={mobileOpen ? "Fermer le menu" : "Ouvrir le menu"}
        aria-expanded={mobileOpen}
        onClick={onToggle}
        className="items-center bg-transparent caret-transparent flex text-[15.3846px] h-[36.5385px] justify-center tracking-[normal] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[color(srgb_1_1_1_/_0.08)] -outline-offset-1 outline outline-1 relative text-center no-underline w-[36.5385px] p-0 rounded-[15369.2px] md:hidden md:text-[14.2222px] md:h-[33.7778px] md:leading-[19.9111px] md:min-h-0 md:min-w-0 md:w-[33.7778px] md:rounded-[14208px]"
      >
        <span className={`bg-white box-border caret-transparent block text-[15.3846px] h-0.5 leading-[21.5385px] outline-[3px] absolute no-underline w-[46%] rounded-sm scale-y-[0.8] transition-transform md:text-[14.2222px] md:leading-[19.9111px] md:transform-none ${mobileOpen ? "rotate-45" : "translate-y-[-3px]"}`}></span>
        <span className={`bg-white box-border caret-transparent block text-[15.3846px] h-0.5 leading-[21.5385px] outline-[3px] absolute no-underline w-[46%] rounded-sm scale-y-[0.8] transition-transform md:text-[14.2222px] md:leading-[19.9111px] md:transform-none ${mobileOpen ? "-rotate-45" : "translate-y-[3px]"}`}></span>
      </button>
    </div>
  );
};

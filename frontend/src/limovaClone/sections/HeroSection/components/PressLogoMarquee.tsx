const clientLogos = Array.from({ length: 8 });

const ClientLogoRow = ({ duplicate = false }: { duplicate?: boolean }) => (
  <div
    role="list"
    aria-hidden={duplicate || undefined}
    className="box-border caret-transparent gap-x-[26.9231px] flex shrink-0 text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[26.9231px] no-underline overflow-hidden md:gap-x-[24.8889px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[24.8889px]"
  >
    {clientLogos.map((_, index) => (
      <div
        key={index}
        role="listitem"
        className="box-border caret-transparent flex h-[56px] w-[104px] shrink-0 items-center justify-center overflow-hidden md:h-[64px] md:w-[120px]"
      >
        <img
          src="/static/images/rg-formations-logo.png"
          alt={duplicate || index > 0 ? "" : "RG Formation"}
          className="box-border caret-transparent inline-block h-full max-w-full object-contain outline-[3px] no-underline w-full"
        />
      </div>
    ))}
  </div>
);

export const PressLogoMarquee = () => {
  return (
    <div className="box-border caret-transparent gap-x-[19.2308px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[19.2308px] no-underline md:gap-x-[17.7778px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[17.7778px]">
      <div className="box-border caret-transparent text-[13.4615px] font-medium tracking-[-0.107692px] leading-[18.8462px] min-h-[auto] min-w-[auto] outline-[3px] text-center no-underline md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px]">
        Ils sont satisfaits
      </div>
      <div className="box-border caret-transparent gap-x-[26.9231px] flex text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] [mask-image:linear-gradient(90deg,rgba(0,0,0,0)_0%,rgb(255,255,255)_12.5%,rgb(255,255,255)_87.5%,rgba(0,0,0,0)_100%)] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[26.9231px] no-underline w-full overflow-hidden md:gap-x-[24.8889px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[24.8889px]">
        <ClientLogoRow />
        <ClientLogoRow duplicate />
      </div>
    </div>
  );
};

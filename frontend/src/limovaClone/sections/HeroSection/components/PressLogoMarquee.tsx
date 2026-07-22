export const PressLogoMarquee = () => {
  return (
    <div className="box-border caret-transparent gap-x-[19.2308px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[19.2308px] no-underline md:gap-x-[17.7778px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[17.7778px]">
      <div className="box-border caret-transparent text-[13.4615px] font-medium tracking-[-0.107692px] leading-[18.8462px] min-h-[auto] min-w-[auto] outline-[3px] text-center no-underline md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px]">
        Ils sont satisfaits
      </div>
      <div
        role="list"
        aria-label="Organismes de formation satisfaits"
        className="flex min-h-[46px] items-center justify-center"
      >
        <div role="listitem" className="flex items-center justify-center">
          <img
            src="/static/images/rg-formations-logo.png"
            alt="RGFormation"
            className="h-auto w-[132px] object-contain md:w-[160px]"
          />
        </div>
      </div>
    </div>
  );
};

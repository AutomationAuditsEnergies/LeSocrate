import CadrenzaLogo from "/src/components/CadrenzaLogo.jsx";

export const FooterBrand = () => {
  return (
    <div className="items-start box-border caret-transparent gap-x-[15.3846px] flex flex-col text-[15.3846px] justify-start tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[15.3846px] no-underline md:items-center md:gap-x-[14.2222px] md:flex-row md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[14.2222px]">
      <a
        href="/"
        className="items-center aspect-[148_/_36] box-border caret-transparent flex shrink-0 text-[15.3846px] justify-center tracking-[-0.107692px] leading-[21.5385px] max-w-full min-h-[auto] min-w-[auto] outline-[3px] no-underline w-[125px] overflow-hidden md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:w-[115.556px]"
      >
        <CadrenzaLogo />
      </a>
    </div>
  );
};

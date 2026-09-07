export const FooterBrand = () => {
  return (
    <div className="items-start box-border caret-transparent gap-x-[15.3846px] flex flex-col text-[15.3846px] justify-start tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[15.3846px] no-underline md:items-center md:gap-x-[14.2222px] md:flex-row md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[14.2222px]">
      <a
        href="/"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-black md:h-9 md:w-9"
        aria-label="Cadrenza, retour à l’accueil"
      >
        <img src="/socrate-mark.svg" alt="" className="h-full w-full object-contain" />
      </a>
    </div>
  );
};

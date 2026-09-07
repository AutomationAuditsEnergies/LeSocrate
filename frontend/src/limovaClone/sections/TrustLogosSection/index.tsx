import { TrustLogoMarquee } from "@/sections/TrustLogosSection/components/TrustLogoMarquee";

export const TrustLogosSection = () => {
  return (
    <section className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
      <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[769.231px] outline-[3px] no-underline w-full mx-auto pt-[38.4615px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[711.111px] md:pt-[53.3333px]">
        <div className="box-border caret-transparent gap-x-[19.2308px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] gap-y-[19.2308px] no-underline md:gap-x-[17.7778px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[17.7778px]">
          <div className="box-border caret-transparent text-[13.4615px] font-medium tracking-[-0.107692px] leading-[18.8462px] min-h-[auto] min-w-[auto] outline-[3px] text-center no-underline md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px]">
            Ils nous font confiance
          </div>
          <TrustLogoMarquee />
        </div>
      </div>
    </section>
  );
};

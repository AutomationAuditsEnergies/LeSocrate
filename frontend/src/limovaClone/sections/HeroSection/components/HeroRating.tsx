import { ShieldCheck } from "lucide-react";

export const HeroRating = () => {
  return (
    <div className="items-center bg-emerald-500/10 box-border caret-transparent gap-x-[10.3846px] flex text-[13.8462px] justify-center tracking-[-0.107692px] leading-[19.3846px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[10.3846px] no-underline w-fit mx-auto px-[12.1154px] py-[8.65385px] rounded-[12.1154px] md:gap-x-[10.6667px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[10.6667px] md:px-[12.4444px] md:py-[8.88889px] md:rounded-[12.4444px]">
      <ShieldCheck aria-hidden="true" className="text-emerald-400" size={16} />
      <div className="box-border caret-transparent text-[10.3846px] tracking-[-0.107692px] leading-[14.5385px] min-h-[auto] min-w-[auto] outline-[3px] no-underline md:text-[10.6667px] md:tracking-[-0.0995556px] md:leading-[14.9333px]">
        Cadre RNCP conservé
      </div>
      <div aria-hidden="true" className="bg-emerald-400 h-[4px] w-[4px] rounded-full" />
      <div className="box-border caret-transparent text-[10.3846px] font-semibold tracking-[-0.107692px] leading-[14.5385px] min-h-[auto] min-w-[auto] outline-[3px] no-underline md:text-[10.6667px] md:tracking-[-0.0995556px] md:leading-[14.9333px]">
        Production traçable
      </div>
    </div>
  );
};

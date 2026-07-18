import { FaqTabs } from "@/sections/FaqSection/components/FaqTabs";
import { FaqList } from "@/sections/FaqSection/components/FaqList";
import { FaqHelpCard } from "@/sections/FaqSection/components/FaqHelpCard";

export const FaqSection = () => {
  return (
    <section id="faq" className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
      <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[653.846px] outline-[3px] no-underline w-full mx-auto pt-[76.9231px] px-[19.2308px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-screen-sm md:pt-[88.8889px] md:px-[35.5556px]">
        <div className="box-border caret-transparent gap-x-[30.7692px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] gap-y-[30.7692px] no-underline md:gap-x-[35.5556px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[35.5556px]">
          <div className="box-border caret-transparent gap-x-[11.5385px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[11.5385px] no-underline md:gap-x-[10.6667px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[10.6667px]">
            <div className="items-center bg-[color(srgb_0.862745_0.556863_0.129412_/_0.08)] box-border caret-transparent text-yellow-600 gap-x-[6.34615px] flex text-[12.6923px] justify-center tracking-[-0.107692px] leading-[17.7692px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[6.34615px] no-underline w-fit mx-auto px-[11.1058px] py-[6.34615px] rounded-[11.1058px] md:gap-x-[7.11111px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[7.11111px] md:px-[12.4444px] md:py-[7.11111px] md:rounded-[12.4444px]">
              <div className="bg-clip-text bg-[linear-gradient(136deg,rgb(241,115,36)_-1.65%,rgb(220,142,33)_100.28%)] box-border text-transparent text-[11.1058px] tracking-[-0.107692px] leading-[15.5481px] min-h-[auto] min-w-[auto] outline-[3px] no-underline uppercase font-geistmono md:text-[12.4444px] md:tracking-[-0.0995556px] md:leading-[17.4222px]">
                F.A.Q
              </div>
            </div>
            <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[769.231px] min-h-[auto] min-w-[auto] outline-[3px] no-underline w-full mb-[3.84615px] mx-auto md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[711.111px] md:mb-[3.55556px]">
              <h2 className="box-border caret-transparent text-[28.7692px] font-semibold tracking-[-1.00692px] leading-[31.6462px] outline-[3px] text-center no-underline font-instrumentsans md:text-[49.7778px] md:tracking-[-1.74222px] md:leading-[54.7556px]">
                Les questions fréquentes
              </h2>
            </div>
            <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] no-underline w-full md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
              <p className="box-border caret-transparent text-[color(srgb_1_1_1_/_0.73)] text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] text-center no-underline md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
                Vous n’êtes jamais seul : chez Cadrenza, l’accompagnement
                personnalisé est au cœur de notre mission.
              </p>
            </div>
          </div>
          <div className="box-border caret-transparent gap-x-[26.9231px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[26.9231px] no-underline md:gap-x-[24.8889px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[24.8889px]">
            <FaqTabs />
            <FaqList />
            <FaqHelpCard />
          </div>
        </div>
      </div>
    </section>
  );
};

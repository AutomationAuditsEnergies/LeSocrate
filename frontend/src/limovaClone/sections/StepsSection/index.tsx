import { StepsContent } from "@/sections/StepsSection/components/StepsContent";
import { ProductPreview } from "@/sections/StepsSection/components/ProductPreview";

export const StepsSection = () => {
  return (
    <section id="methode" className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
      <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[1192.31px] outline-[3px] relative no-underline w-full z-[1] mx-auto px-[19.2308px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[1137.78px] md:px-[35.5556px]">
        <div className="box-border caret-transparent gap-x-[38.4615px] grid text-[15.3846px] grid-cols-[repeat(1,minmax(0px,1fr))] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] gap-y-[38.4615px] no-underline md:gap-x-[35.5556px] md:text-[14.2222px] md:grid-cols-[repeat(2,minmax(0px,1fr))] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[35.5556px]">
          <ProductPreview />
          <StepsContent />
        </div>
      </div>
    </section>
  );
};

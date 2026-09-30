import { TestimonialsHeader } from "@/sections/TestimonialsSection/components/TestimonialsHeader";
import { TestimonialGrid } from "@/sections/TestimonialsSection/components/TestimonialGrid";

export const TestimonialsSection = () => {
  return (
    <section id="classe" className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
      <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[1192.31px] outline-[3px] no-underline w-full mx-auto pt-[76.9231px] px-[19.2308px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[1137.78px] md:pt-[88.8889px] md:px-[35.5556px]">
        <div className="box-border caret-transparent gap-x-[38.4615px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] gap-y-[38.4615px] no-underline md:gap-x-[53.3333px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[53.3333px]">
          <TestimonialsHeader />
          <TestimonialGrid />
        </div>
      </div>
    </section>
  );
};

import { Navbar } from "@/sections/Navbar";
import { MainContent } from "@/sections/MainContent";

export const Page = () => {
  return (
    <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline overflow-clip md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
      <div className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] fixed no-underline left-0 top-0 md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]"></div>
      <Navbar />
      <MainContent />
    </div>
  );
};

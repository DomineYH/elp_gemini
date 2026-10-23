/** @type {import('tailwindcss').Config} */
module.exports = {
  // app/static/js/lib/** (pdf.js)는 Tailwind 클래스가 없어 제외
  content: ["./app/templates/**/*.html", "./app/static/js/*.js"],
  plugins: [require("@tailwindcss/typography")],
};

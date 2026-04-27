/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        accent: '#185FA5',
        'accent-hover': '#0C447C',
        'accent-light': '#E6F1FB',
      },
    },
  },
  plugins: [],
}
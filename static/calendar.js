// static/calendar.js

let currentDate = new Date(); // текущая дата
const monthNames = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const colors = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"];

function renderCalendar() {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    document.getElementById("monthYear").textContent = monthNames[month] + " " + year;

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay() || 7;

    const calendarDays = document.getElementById("calendarDays");
    calendarDays.innerHTML = '';

    // Названия дней недели
    ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].forEach(day => {
        const div = document.createElement('div');
        div.className = 'day-name';
        div.textContent = day;
        calendarDays.appendChild(div);
    });

    // Пустые дни до начала месяца
    for (let i = 1; i < startingDayOfWeek; i++) {
        const div = document.createElement('div');
        div.className = 'calendar-day empty';
        calendarDays.appendChild(div);
    }

    // Дни месяца
    for (let day = 1; day <= daysInMonth; day++) {
        const div = document.createElement('div');
        div.className = 'calendar-day';
        div.textContent = day;

        // Сегодняшний день
        const today = new Date();
        if (day === today.getDate() && month === today.getMonth() && year === today.getFullYear()) {
            div.classList.add('today');
        }

        // Клик по дню → добавление праздника
        div.onclick = function() {
            const selectedDate = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            window.location.href = `/calendar/add?date=${selectedDate}`;
        };

        calendarDays.appendChild(div);
    }

    // Подгрузка реальных событий и цветных точек
    loadEvents(year, month + 1);
}

async function loadEvents(year, month) {
    try {
        const response = await fetch(`/calendar/events/${year}/${month}`);
        const events = await response.json(); // { "15": 3, "25": 1 }

        document.querySelectorAll('.calendar-day').forEach(day => {
            const dayNum = day.textContent.trim();
            if (events[dayNum]) {
                day.classList.add('has-events');

                const dotsContainer = document.createElement('div');
                dotsContainer.className = 'event-dots';

                const count = events[dayNum];
                for (let i = 0; i < Math.min(count, colors.length); i++) {
                    const dot = document.createElement('span');
                    dot.className = 'event-dot';
                    dot.style.backgroundColor = colors[i];
                    dotsContainer.appendChild(dot);
                }

                if (count > colors.length) {
                    const more = document.createElement('span');
                    more.textContent = `+${count - colors.length}`;
                    more.style.fontSize = '0.7rem';
                    more.style.color = '#ef4444';
                    dotsContainer.appendChild(more);
                }

                day.appendChild(dotsContainer);
            }
        });
    } catch (error) {
        console.error("Ошибка загрузки событий:", error);
    }
}

function prevMonth() {
    currentDate.setMonth(currentDate.getMonth() - 1);
    renderCalendar();
}

function nextMonth() {
    currentDate.setMonth(currentDate.getMonth() + 1);
    renderCalendar();
}

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    renderCalendar();
});
# Use an official Python runtime as a parent image
FROM python:3.8   

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install mysqlclient
# Copy the current directory contents into the container at /app
COPY . /app/

# Expose the port that Django will run on
EXPOSE 8000

# Run the specified command within the container
CMD ["sh", "-c", "python3 manage.py makemigrations --noinput && python3 manage.py migrate --noinput && python3 manage.py collectstatic --noinput && python manage.py runserver 0.0.0.0:8000"]

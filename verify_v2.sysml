package 'Hospital Management System Use Case' {

    // Actor Definitions
    part def 'Patient';
    part def 'Admin' specializes 'Staff';
    part def 'Doctor';
    part def 'Staff';

    package 'Hospital Management System' {
        part def 'Hospital Management System';

        // Use Case Definitions
        use case def 'Login' {
            subject system : 'Hospital Management System';
            actor patient : 'Patient';
        }

        use case def 'Register' {
            subject system : 'Hospital Management System';
            actor patient : 'Patient';
            include use case 'Login';
        }

        use case def 'View Profile' {
            subject system : 'Hospital Management System';
            actor doctor : 'Doctor';
            // Condition: user requests profile
            extend use case 'Login';
        }

        use case def 'Update Database' {
            subject system : 'Hospital Management System';
            actor staff : 'Staff';
        }

        use case def 'Maintain Database' specializes 'Update Database' {
            subject system : 'Hospital Management System';
            actor admin : 'Admin';
        }

        use case def 'Pay Hospital Dues' {
            subject system : 'Hospital Management System';
        }

    }
}